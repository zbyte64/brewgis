# ruff: noqa: ANN201, ARG002
"""Tests for the staging model generator service."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.db import connection

from brewgis.workspace.services.column_inspector import inspect_table
from brewgis.workspace.services.staging_model import generate_base_canvas_stub
from brewgis.workspace.services.staging_model import generate_parcel_staging
from brewgis.workspace.services.staging_model import write_base_canvas_stub
from brewgis.workspace.services.staging_model import write_parcel_staging


@pytest.fixture
def parcel_table_full(db) -> str:
    """Create a full parcel table with all required columns."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_stage_full (
                id SERIAL PRIMARY KEY,
                built_form_key INTEGER,
                intersection_density FLOAT,
                land_development_category VARCHAR(64),
                geom GEOMETRY(POLYGON, 4326),
                some_extra_col VARCHAR(32)
            )
            """
        )
    yield "public.test_stage_full"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_stage_full CASCADE")


@pytest.fixture
def parcel_table_minimal(db) -> str:
    """Create a minimal parcel table with only id and geom."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_stage_min (
                gid SERIAL PRIMARY KEY,
                geometry GEOMETRY(POLYGON, 4326)
            )
            """
        )
    yield "public.test_stage_min"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_stage_min CASCADE")


@pytest.mark.integration
class TestGenerateParcelStaging:
    """Tests for :func:`generate_parcel_staging`."""

    def test_uses_detected_id_column(self, parcel_table_full):
        """The staging SQL maps the detected ID column to parcel_id and id."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_full", info)
        assert "id AS parcel_id" in sql
        assert "id AS id" in sql

    def test_provides_default_built_form_key(self, parcel_table_minimal):
        """When built_form_key is missing, a default is supplied."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_min", info)
        assert "2 AS built_form_key" in sql

    def test_passes_through_built_form_key(self, parcel_table_full):
        """When built_form_key exists, it is passed through verbatim."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_full", info)
        assert "built_form_key," in sql
        assert "2 AS built_form_key" not in sql

    def test_provides_default_intersection_density(self, parcel_table_minimal):
        """When intersection_density is missing, a computed default is supplied."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_min", info)
        assert "intersection_density" in sql
        assert "0.5" in sql or "LEAST" in sql

    def test_passes_through_intersection_density(self, parcel_table_full):
        """When intersection_density exists, it passes through."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_full", info)
        assert "intersection_density," in sql

    def test_provides_default_land_dev_category(self, parcel_table_minimal):
        """When land_development_category is missing, 'standard' is default."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_min", info)
        assert "'standard' AS land_development_category" in sql

    def test_passes_through_extra_columns(self, parcel_table_full):
        """Extra columns (not in the required set) are passed through."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_full", info)
        assert "some_extra_col" in sql

    def test_is_valid_dbt_template(self, parcel_table_full):
        """Generated SQL is a valid dbt template (starts with config, uses vars)."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_full", info)
        assert "{{ config(materialized='view') }}" in sql
        assert "{{ var('source_schema'" in sql
        assert "{{ var('raw_table'" in sql

    def test_writes_to_disk(self, parcel_table_full):
        """write_parcel_staging creates the file on disk."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        filename = write_parcel_staging("public", "test_stage_full", info)
        path = Path("brewgis/dbt_project/models/staging") / filename
        assert path.exists()
        content = path.read_text()
        assert "AUTO-GENERATED" in content

    def test_gid_column_mapping(self, parcel_table_minimal):
        """Minimal table with gid column maps to parcel_id and id."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_parcel_staging("public", "test_stage_min", info)
        assert "gid AS parcel_id" in sql
        assert "gid AS id" in sql


@pytest.mark.integration
class TestGenerateBaseCanvasStub:
    """Tests for :func:`generate_base_canvas_stub`."""

    def test_produces_all_base_canvas_columns(self, parcel_table_minimal):
        """The stub SQL includes all base canvas columns with zero defaults."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_base_canvas_stub("public", "test_stage_min", info)
        # Should have parcel_id and id
        assert "parcel_id" in sql
        assert "0.0 AS du" in sql
        assert "0.0 AS pop" in sql
        assert "0.0 AS hh" in sql
        assert "0.0 AS emp" in sql

    def test_computes_area_gross(self, parcel_table_minimal):
        """area_gross is computed from geometry."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_base_canvas_stub("public", "test_stage_min", info)
        assert "ST_Area" in sql
        assert "area_gross" in sql

    def test_provides_default_land_dev_category(self, parcel_table_minimal):
        """land_development_category defaults to 'standard' when missing."""
        info = inspect_table("public", "test_stage_min")
        assert info is not None
        sql = generate_base_canvas_stub("public", "test_stage_min", info)
        assert "'standard' AS land_development_category" in sql

    def test_writes_to_disk(self, parcel_table_full):
        """write_base_canvas_stub creates the file on disk."""
        info = inspect_table("public", "test_stage_full")
        assert info is not None
        filename = write_base_canvas_stub("public", "test_stage_full", info)
        path = Path("brewgis/dbt_project/models/staging") / filename
        assert path.exists()
        content = path.read_text()
        assert "AUTO-GENERATED" in content
