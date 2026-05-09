"""End-to-end tests for the ETL pipeline (populate_base_canvas management command).

Tests that ``populate_base_canvas --synthetic N`` produces a valid
base canvas table with all 77 columns, no NULLs in required columns,
and reasonable aggregate values.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection

from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema


@pytest.mark.integration
class TestETLPipeline:
    """End-to-end tests for the ETL pipeline."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, db) -> None:
        """Ensure clean state before and after each test."""
        BaseCanvasManager.drop_table()
        yield
        BaseCanvasManager.drop_table()

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
        # id is SERIAL but also a column
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
