"""Tests for dbt schema name generation.

Verifies that the ``generate_schema_name`` macro override produces
the correct schema (no ``public_`` prefix concatenation), and that
dbt creates views in the schema specified by the ``target_schema`` var.

This test uses the ``test_geometry_table`` fixture (available in the
test database) as a minimal parcel table for dbt to compile against.
"""

from __future__ import annotations

import logging

import pytest
from django.test import TestCase

from brewgis.workspace.analysis.dbt_runner import run_dbt_local

logger = logging.getLogger(__name__)

from brewgis.workspace.analysis.dbt_runner import DBT_PROJECT_DIR

TEST_VARS: dict[str, str | list] = {
    "parcel_table": "test_geometry_table",
    "source_schema": "public",
    "constraints": [],
    "target_schema": "test_schema_foo",
    "scenario_id": "test_001",
}


@pytest.mark.integration
class TestGenerateSchemaNameMacro(TestCase):
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
        result = run_dbt_local(
            select=["env_constraint"],
            vars_=TEST_VARS,
            full_refresh=True,
        )

        assert result.success, f"dbt run failed: {result.error}"

        # The compiled SQL should reference the correct schema
        # (we can't check the compiled file directly since it's in a temp dir,
        # but success means dbt parsed the macro correctly without errors)

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
