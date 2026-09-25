# ruff: noqa: ANN201, S608
"""Tests for the data export module (BuildingType → PostGIS tables)."""

from __future__ import annotations

import json

import pytest
from django.db import connection
from django.test import TestCase

from brewgis.workspace.analysis.data_export import ensure_export_exists
from brewgis.workspace.analysis.data_export import export_building_types
from tests.factories import BuildingTypeFactory
from tests.factories import WorkspaceFactory

TEST_SCHEMA = "public"
TEST_TABLE = "test_export_bt"


@pytest.mark.integration
class TestExportBuildingTypes(TestCase):
    """Tests for :func:`export_building_types`."""

    def setUp(self):
        self.workspace = WorkspaceFactory()

    def tearDown(self):
        """Clean up the test table after each test."""
        with connection.cursor() as cursor:
            cursor.execute(
                f'DROP TABLE IF EXISTS "{TEST_SCHEMA}"."{TEST_TABLE}" CASCADE'
            )
        super().tearDown()

    def test_creates_table_with_expected_columns(self) -> None:
        """Export creates a table with the correct column set."""
        BuildingTypeFactory.create_batch(3, workspace=self.workspace)

        count = export_building_types(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 3

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                [TEST_SCHEMA, TEST_TABLE],
            )
            columns = [row[0] for row in cursor.fetchall()]

        expected = [
            "id",
            "key",
            "land_development_category",
            "du_per_acre",
            "emp_per_acre",
            "far",
            "household_size",
            "vacancy_rate",
            "jobs_by_sector",
            "indoor_water_rate",
            "outdoor_water_rate",
            "irrigable_area_fraction",
            "building_coverage",
            "electricity_eui",
            "gas_eui",
            "vintage",
            "trip_rate_override",
            "ite_land_use_code",
            "pass_by_trip_pct",
        ]
        assert columns == expected

    def test_export_of_a_table_predating_the_category_column(self) -> None:
        """An older table regains the column, with its values aligned by name."""
        BuildingTypeFactory(
            workspace=self.workspace,
            name="Urban One",
            du_per_acre=21.0,
            land_development_category="urban",
        )
        BuildingTypeFactory(
            workspace=self.workspace,
            name="Crop One",
            du_per_acre=0.0,
            land_development_category="agricultural",
        )
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
        # the shape a table exported by the previous release has: the column the
        # export grew later is absent and the next export appends it
        with connection.cursor() as cursor:
            cursor.execute(
                f'ALTER TABLE "{TEST_SCHEMA}"."{TEST_TABLE}" '
                "DROP COLUMN land_development_category"
            )

        count = export_building_types(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 2

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT key, du_per_acre, land_development_category FROM "
                f'"{TEST_SCHEMA}"."{TEST_TABLE}" ORDER BY key'
            )
            rows = cursor.fetchall()
        # key/du_per_acre/category all survive together: the export inserts into
        # named columns, so the ALTER-appended column cannot shift a value
        assert rows == [
            ("Crop One", 0.0, "agricultural"),
            ("Urban One", 21.0, "urban"),
        ]

    def test_ensure_export_rebuilds_a_table_missing_a_column(self) -> None:
        """A populated table without the current column set is re-exported."""
        BuildingTypeFactory.create_batch(2, workspace=self.workspace)
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
        with connection.cursor() as cursor:
            cursor.execute(
                f'ALTER TABLE "{TEST_SCHEMA}"."{TEST_TABLE}" '
                "DROP COLUMN land_development_category"
            )

        count = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )

        assert count == 2
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                [TEST_SCHEMA, TEST_TABLE],
            )
            columns = {row[0] for row in cursor.fetchall()}
        assert "land_development_category" in columns

    def test_ensure_export_rebuilds_a_table_of_stale_rows(self) -> None:
        """A built form edited since the last export is re-exported."""
        building_type = BuildingTypeFactory(
            workspace=self.workspace,
            name="Crop One",
            jobs_by_sector={"agriculture": 100.0},
        )
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
        building_type.jobs_by_sector = {"military": 100.0}
        building_type.save(update_fields=["jobs_by_sector", "updated_at"])

        assert (
            ensure_export_exists(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
            == 1
        )

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT jobs_by_sector FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert json.loads(cursor.fetchone()[0]) == {"military": 100.0}

        # and a table already holding the current rows is left alone
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
        assert (
            ensure_export_exists(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
            == 1
        )

    def test_all_building_types_exported(self) -> None:
        """All BuildingType rows appear in the output table."""
        BuildingTypeFactory.create_batch(7, workspace=self.workspace)

        count = export_building_types(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 7

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            row_count = cursor.fetchone()[0]
        assert row_count == 7

    def test_force_recreate_drops_and_recreates(self) -> None:
        """force_recreate=True drops the table and creates it fresh."""
        BuildingTypeFactory.create_batch(3, workspace=self.workspace)
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)
        BuildingTypeFactory.create_batch(2, workspace=self.workspace)

        # force_recreate should produce only the pre-existing batch
        count = export_building_types(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE, force_recreate=True
        )
        assert count == 5

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            row_count = cursor.fetchone()[0]
        assert row_count == 5

    def test_empty_building_type_table_creates_empty_table(self) -> None:
        """No BuildingTypes → table is created with 0 rows."""
        count = export_building_types(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 0

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                [TEST_SCHEMA, TEST_TABLE],
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert cursor.fetchone()[0] == 0

    def test_coalesce_converts_null_to_zero(self) -> None:
        """Nullable fields with None become 0.0 in the output."""
        # Create a BuildingType with all nullable fields left as None
        # (factory defaults override some, so we explicitly set them).
        bt = BuildingTypeFactory(
            workspace=self.workspace,
            du_per_acre=None,
            emp_per_acre=None,
            far=None,
            indoor_water_rate=None,
            outdoor_water_rate=None,
            irrigable_area_fraction=None,
            building_coverage=None,
            electricity_eui=None,
            gas_eui=None,
            trip_rate_override=None,
        )

        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)

        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT * FROM "{TEST_SCHEMA}"."{TEST_TABLE}" WHERE id = %s',
                [bt.pk],
            )
            row = cursor.fetchone()
            assert row is not None

            # Map column index to name by fetching column metadata
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                [TEST_SCHEMA, TEST_TABLE],
            )
            col_names = [r[0] for r in cursor.fetchall()]
            row_dict = dict(zip(col_names, row, strict=False))

            # Every _NULLABLE_TO_ZERO column should be 0.0
            nullable = {
                "du_per_acre",
                "emp_per_acre",
                "far",
                "indoor_water_rate",
                "outdoor_water_rate",
                "irrigable_area_fraction",
                "building_coverage",
                "electricity_eui",
                "gas_eui",
                "trip_rate_override",
            }
            for col in nullable:
                assert row_dict[col] == 0.0, (
                    f"Expected {col}=0.0, got {row_dict[col]!r}"
                )

            # Non-nullable COALESCE columns should keep their default values
            assert row_dict["household_size"] == 2.5
            assert row_dict["vacancy_rate"] == 5.0
            assert row_dict["pass_by_trip_pct"] == 0.0

    def test_jobs_by_sector_is_jsonb(self) -> None:
        """jobs_by_sector is exported as a JSONB column."""
        BuildingTypeFactory(
            workspace=self.workspace, jobs_by_sector={"retail": 40.0, "office": 60.0}
        )
        export_building_types(self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                  AND column_name = 'jobs_by_sector'
                """,
                [TEST_SCHEMA, TEST_TABLE],
            )
            data_type = cursor.fetchone()[0]
        assert data_type == "jsonb"


@pytest.mark.integration
class TestEnsureExportExists(TestCase):
    """Tests for :func:`ensure_export_exists`."""

    def setUp(self):
        self.workspace = WorkspaceFactory()

    def tearDown(self):
        """Clean up the test table after each test."""
        with connection.cursor() as cursor:
            cursor.execute(
                f'DROP TABLE IF EXISTS "{TEST_SCHEMA}"."{TEST_TABLE}" CASCADE'
            )
        super().tearDown()

    def test_creates_table_on_first_call(self) -> None:
        """First call creates the table when it does not exist."""
        BuildingTypeFactory.create_batch(3, workspace=self.workspace)
        count = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 3

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert cursor.fetchone()[0] == 3

    def test_second_call_re_exports_when_rows_changed(self) -> None:
        """Building Types added since the last export reach the table."""
        BuildingTypeFactory.create_batch(2, workspace=self.workspace)
        count1 = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count1 == 2

        # the table is a cache of the workspace's Building Types, so rows added
        # since the last export have to be exported, not served around
        BuildingTypeFactory.create_batch(3, workspace=self.workspace)
        count2 = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count2 == 5

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert cursor.fetchone()[0] == 5

    def test_re_exports_when_table_is_empty(self) -> None:
        """If the table exists but is empty, it re-exports."""
        BuildingTypeFactory.create_batch(3, workspace=self.workspace)

        # First export populates the table
        count1 = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count1 == 3

        # Manually truncate to simulate an empty table
        with connection.cursor() as cursor:
            cursor.execute(f'TRUNCATE TABLE "{TEST_SCHEMA}"."{TEST_TABLE}"')

        # A new BuildingType was created in the meantime
        BuildingTypeFactory.create_batch(2, workspace=self.workspace)

        # ensure_export_exists should re-export because the table is now empty
        count2 = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count2 == 5

        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert cursor.fetchone()[0] == 5

    def test_empty_database_creates_empty_table(self) -> None:
        """No BuildingType records → table is created with 0 rows."""
        count = ensure_export_exists(
            self.workspace, schema=TEST_SCHEMA, table=TEST_TABLE
        )
        assert count == 0

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s",
                [TEST_SCHEMA, TEST_TABLE],
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(f'SELECT COUNT(*) FROM "{TEST_SCHEMA}"."{TEST_TABLE}"')
            assert cursor.fetchone()[0] == 0
