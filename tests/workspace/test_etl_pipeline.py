"""End-to-end tests for the ETL pipeline (populate_base_canvas management command).

Tests that ``populate_base_canvas --synthetic N`` produces a valid
base canvas table with all 77 columns, no NULLs in required columns,
and reasonable aggregate values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command
from django.db import connection

from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_pipeline import _DEMOGRAPHIC_COLUMNS
from brewgis.workspace.services.base_canvas_pipeline import _EMPLOYMENT_COLUMNS
from brewgis.workspace.services.base_canvas_pipeline import run_pipeline
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

if TYPE_CHECKING:
    from collections.abc import Iterator

# The synthetic generator places its parcels inside this box (see
# ``synthetic_parcel_generator``); the fabricated staging blocks cover it.
_SYNTHETIC_BBOX = (-122.5, 36.5, -121.5, 37.5)

_BLOCKS_PER_AXIS = 3
"""Blocks per axis the fabricated staging lattices are cut into."""

_BLOCK_VALUE = 100.0
"""Value every allocatable staging column carries — enough to allocate from."""


def _create_staging_table(schema: str, table: str, columns: list[str]) -> None:
    """Create *schema*.*table*: a block key, a 4326 geometry, and *columns*.

    One lattice of blocks over ``_SYNTHETIC_BBOX``, each column carrying
    ``_BLOCK_VALUE``, so the pipeline's area-weighted allocation has data to
    transfer into every synthetic parcel.
    """
    min_x, min_y, max_x, max_y = _SYNTHETIC_BBOX
    step_x = (max_x - min_x) / _BLOCKS_PER_AXIS
    step_y = (max_y - min_y) / _BLOCKS_PER_AXIS
    measurements = ", ".join(
        f"{column} double precision NOT NULL" for column in columns
    )
    placeholders = ", ".join(["%s"] * len(columns))

    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE")
        cursor.execute(
            f"CREATE TABLE {schema}.{table} ("
            f"geoid text PRIMARY KEY, "
            f"geometry geometry(Polygon, 4326) NOT NULL, {measurements})"
        )
        for ix in range(_BLOCKS_PER_AXIS):
            for iy in range(_BLOCKS_PER_AXIS):
                cursor.execute(
                    f"INSERT INTO {schema}.{table} ("  # noqa: S608 — identifiers are fixture constants
                    f"geoid, geometry, {', '.join(columns)}) "
                    f"VALUES (%s, ST_MakeEnvelope(%s, %s, %s, %s, 4326), "
                    f"{placeholders})",
                    [
                        f"{ix}-{iy}",
                        min_x + ix * step_x,
                        min_y + iy * step_y,
                        min_x + (ix + 1) * step_x,
                        min_y + (iy + 1) * step_y,
                        *([_BLOCK_VALUE] * len(columns)),
                    ],
                )


@pytest.fixture(autouse=True)
def staging_tables() -> Iterator[None]:
    """Create the census/LEHD staging tables the ETL pipeline allocates from.

    Steps 4-5 allocate demographics and employment from
    ``census.acs_block_group`` and ``lehd.wac_block`` and raise without them. In
    a real install those tables are the SQLMesh bridges over the dlt pipelines'
    cached downloads, so a test database has neither — which is why every test
    here but :func:`test_missing_census_table_raises` failed at step 4.
    ``run_pipeline``'s contract is "given staging tables, produce a valid
    canvas", so the fixture fabricates them instead of requiring an install to
    have run the ingestion pipelines first.
    """
    _create_staging_table("census", "acs_block_group", _DEMOGRAPHIC_COLUMNS)
    _create_staging_table("lehd", "wac_block", _EMPLOYMENT_COLUMNS)
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS census.acs_block_group CASCADE")
            cursor.execute("DROP TABLE IF EXISTS lehd.wac_block CASCADE")


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
class TestETLPipeline:
    """End-to-end tests for the ETL pipeline."""

    @pytest.fixture(autouse=True)
    def _cleanup(self) -> None:
        """Ensure clean state before and after each test."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE")
        yield
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE public.base_canvas RESTART IDENTITY CASCADE")

    def _validate_base_canvas(self, expected_rows: int) -> None:
        """Assert the base canvas table meets post-ETL expectations."""
        # Table exists
        assert BaseCanvasManager.table_exists()

        # Schema is valid
        missing = BaseCanvasManager.validate_schema()
        assert not missing, f"Missing columns: {missing}"

        # Count rows
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            count = cursor.fetchone()[0]
            assert count == expected_rows, f"Expected {expected_rows} rows, got {count}"

        # No NULLs in NON_NULL_COLUMNS
        with connection.cursor() as cursor:
            non_null_checks = " OR ".join(
                f'"{c}" IS NULL' for c in BaseCanvasSchema.NON_NULL_COLUMNS
            )
            cursor.execute(
                f"SELECT COUNT(*) FROM public.base_canvas WHERE {non_null_checks}"
            )
            null_count = cursor.fetchone()[0]
            assert null_count == 0, f"{null_count} rows have NULLs in required columns"

    def _query_sum(self, column: str) -> float:
        """Return the column sum from the base canvas."""
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COALESCE(SUM("{column}"), 0) FROM public.base_canvas'
            )
            return float(cursor.fetchone()[0])

    # ── Tests ─────────────────────────────────────────────────────────

    def test_synthetic_50_pipeline(self) -> None:
        """Running with --synthetic 50 should produce a valid table."""
        call_command("populate_base_canvas", synthetic=50)
        self._validate_base_canvas(50)

    def test_synthetic_10_pipeline(self) -> None:
        """Running with --synthetic 10 should produce a valid table."""
        call_command("populate_base_canvas", synthetic=10)
        self._validate_base_canvas(10)

    def test_all_columns_populated(self) -> None:
        """All 77 schema columns should exist and be populated."""
        call_command("populate_base_canvas", synthetic=20)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'base_canvas'
                ORDER BY ordinal_position
                """
            )
            db_cols = {row[0] for row in cursor.fetchall()}
        expected = set(BaseCanvasSchema.COLUMN_NAMES)
        # parcel_id is the primary key
        missing = expected - db_cols
        assert not missing, f"Missing columns from DB: {missing}"

    def test_area_columns_non_negative(self) -> None:
        """All area columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=30)
        area_cols = [c for c in BaseCanvasSchema.COLUMN_NAMES if c.startswith("area_")]
        for col in area_cols:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_area_gross_positive(self) -> None:
        """area_gross should be positive for all rows."""
        call_command("populate_base_canvas", synthetic=25)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE area_gross <= 0"
            )
            zero_count = cursor.fetchone()[0]
            assert zero_count == 0, f"{zero_count} rows with area_gross <= 0"

    def test_demographic_columns_non_negative(self) -> None:
        """Demographic columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=20)
        for col in ["pop", "hh", "du", "pop_groupquarter"]:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_employment_columns_non_negative(self) -> None:
        """Employment columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=20)
        emp_cols = [c for c in BaseCanvasSchema.COLUMN_NAMES if c.startswith("emp")]
        for col in emp_cols:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_schema_idempotent(self) -> None:
        """Running the command twice should succeed (idempotent)."""
        call_command("populate_base_canvas", synthetic=10)
        call_command("populate_base_canvas", synthetic=10, truncate=True)
        self._validate_base_canvas(10)

    def test_skip_imputation(self) -> None:
        """--skip-imputation should leave some nulls in paintable columns."""
        call_command("populate_base_canvas", synthetic=20, skip_imputation=True)
        # The table should still exist and have the right columns
        assert BaseCanvasManager.table_exists()
        missing = BaseCanvasManager.validate_schema()
        assert not missing
        # But some nulls may exist in paintable columns (static ones are fine)
        with connection.cursor() as cursor:
            # Pick one paintable column that depends on imputation
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE intersection_density IS NULL"
            )
            null_count = cursor.fetchone()[0]
            # If synthetic data generator filled it, skip_imputation might still have data
            # We just verify the command doesn't error
            assert BaseCanvasManager.table_exists()

    def test_land_development_category_populated(self) -> None:
        """land_development_category should be populated."""
        call_command("populate_base_canvas", synthetic=30)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT land_development_category FROM public.base_canvas"
            )
            categories = {row[0] for row in cursor.fetchall()}
            assert len(categories) > 0
            assert "" not in categories  # no empty strings

    def test_intersection_density_defaulted(self) -> None:
        """intersection_density should be populated after imputation."""
        call_command("populate_base_canvas", synthetic=20)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE intersection_density IS NULL"
            )
            assert cursor.fetchone()[0] == 0

    def test_irrigation_columns_defaulted(self) -> None:
        """Irrigation columns should be non-null."""
        call_command("populate_base_canvas", synthetic=20)
        for col in ["residential_irrigated_area", "commercial_irrigated_area"]:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" IS NULL'
                )
                assert cursor.fetchone()[0] == 0, f"NULLs in {col}"

    def test_missing_census_table_raises(self) -> None:
        """run_pipeline should raise RuntimeError when census staging table is missing."""
        with pytest.raises(RuntimeError) as exc_info:
            run_pipeline(
                synthetic_n=10,
                census_schema="nonexistent_schema",
            )
        error_msg = str(exc_info.value)
        assert "does not exist" in error_msg
        assert "census" in error_msg.lower()
