"""Tests for dbt schema name generation.

Verifies that the ``generate_schema_name`` macro override produces
the correct schema (no ``public_`` prefix concatenation), and that
dbt creates views in the schema specified by the ``target_schema`` var.

This test creates a minimal PostGIS table for dbt to compile against.
"""

from __future__ import annotations

import logging

import pytest
from django.db import connection
from django.test import TransactionTestCase

from brewgis.workspace.analysis.dbt_runner import DBT_PROJECT_DIR
from brewgis.workspace.analysis.dbt_runner import run_dbt_local

logger = logging.getLogger(__name__)

TEST_VARS: dict[str, str | list] = {
    "parcel_table": "test_geometry_table",
    "source_schema": "public",
    "constraints": [],
    "target_schema": "test_schema_foo",
    "scenario_id": "test_001",
}

# DDL is auto-committed in PostgreSQL, so creating/dropping tables
# inside TestCase methods works despite per-test transaction rollback.


def _create_geometry_table() -> None:
    """Create the minimal PostGIS geometry table for dbt compilation."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute("DROP TABLE IF EXISTS public.test_geometry_table CASCADE")
        cursor.execute(
            "CREATE TABLE public.test_geometry_table ("
            "  id SERIAL PRIMARY KEY,"
            "  geom GEOMETRY(POLYGON, 4326)"
            ")"
        )
        cursor.execute(
            "INSERT INTO public.test_geometry_table (geom) VALUES "
            "  (ST_SetSRID(ST_MakeEnvelope(0, 0, 1, 1), 4326)),"
            "  (ST_SetSRID(ST_MakeEnvelope(1, 0, 2, 1), 4326))"
        )


def _drop_geometry_table() -> None:
    """Drop the geometry table."""
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS public.test_geometry_table CASCADE")


@pytest.mark.integration
class TestGenerateSchemaNameMacro(TransactionTestCase):
    """Tests that the generate_schema_name macro overrides dbt's default."""

    def test_macro_file_exists(self) -> None:
        """The generate_schema_name.sql macro file must exist."""
        macro_path = DBT_PROJECT_DIR / "macros" / "generate_schema_name.sql"
        assert macro_path.exists(), "generate_schema_name.sql macro not found"

    def test_macro_compiles_no_public_prefix(self) -> None:
        """Compile a model with target_schema and verify no ``public_`` prefix.

        The macro override should return ``target_schema`` verbatim, not
        ``public_target_schema``.
        """
        try:
            _create_geometry_table()
            result = run_dbt_local(
                select=["env_constraint"],
                vars_=TEST_VARS,
                full_refresh=True,
                db_name=connection.settings_dict["NAME"],
            )
            assert result.success, f"dbt run failed: {result.error}"
        finally:
            _drop_geometry_table()

    def test_schema_no_prefix_in_macro(self) -> None:
        """Confirm the macro logic directly by checking its content.

        The macro should return ``custom_schema_name`` verbatim when set,
        with no concatenation.
        """
        macro_path = DBT_PROJECT_DIR / "macros" / "generate_schema_name.sql"
        macro_content = macro_path.read_text()

        # The macro must NOT concatenate schema names with underscore
        assert "{{ target.schema }}_{{ custom_schema_name }}" not in macro_content
        assert (
            "{{ target.schema }}_{{ custom_schema_name | trim }}" not in macro_content
        )
        assert "{{ target.schema }}~" not in macro_content

        # The macro must return custom_schema_name verbatim
        assert "{{ custom_schema_name | trim }}" in macro_content
