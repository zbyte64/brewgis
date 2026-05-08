# ruff: noqa: ANN201, ARG002
"""Tests for the column inspector service."""

from __future__ import annotations

import pytest

from django.db import connection

from brewgis.workspace.services.column_inspector import inspect_table


@pytest.fixture
def empty_table(db) -> str:
    """Create a table with no geometry or ID column."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_no_geom (
                name VARCHAR(64),
                value FLOAT
            )
            """
        )
    yield "public.test_no_geom"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_no_geom CASCADE")


@pytest.fixture
def full_table(db) -> str:
    """Create a table with id, geom, and all required columns."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_full (
                id SERIAL PRIMARY KEY,
                built_form_key INTEGER DEFAULT 2,
                intersection_density FLOAT DEFAULT 10.0,
                land_development_category VARCHAR(64) DEFAULT 'standard',
                geometry GEOMETRY(POLYGON, 4326),
                custom_field VARCHAR(128)
            )
            """
        )
    yield "public.test_full"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_full CASCADE")


@pytest.fixture
def gid_table(db) -> str:
    """Create a table with a non-standard ID column name."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_gid (
                gid SERIAL PRIMARY KEY,
                geom GEOMETRY(POLYGON, 4326)
            )
            """
        )
    yield "public.test_gid"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_gid CASCADE")


@pytest.mark.integration
class TestInspectTable:
    """Tests for :func:`inspect_table`."""

    def test_returns_none_for_missing_table(self, db):
        """A non-existent table returns None."""
        result = inspect_table("public", "table_does_not_exist_xyz")
        assert result is None

    def test_detects_columns_and_types(self, full_table):
        """Column names and types are returned correctly."""
        info = inspect_table("public", "test_full")
        assert info is not None
        assert "id" in info.columns
        assert "geometry" in info.columns
        assert "custom_field" in info.columns
        assert info.columns["id"].startswith("integer")

    def test_detects_id_column(self, full_table):
        """id is detected as the ID column."""
        info = inspect_table("public", "test_full")
        assert info is not None
        assert info.id_column == "id"

    def test_detects_gid_column(self, gid_table):
        """gid is detected as the ID column when id is absent."""
        info = inspect_table("public", "test_gid")
        assert info is not None
        assert info.id_column == "gid"

    def test_no_id_column(self, empty_table):
        """Table without ID column returns id_column=None."""
        info = inspect_table("public", "test_no_geom")
        assert info is not None
        assert info.id_column is None

    def test_has_geom_true(self, full_table, gid_table):
        """has_geom is True for tables with geometry column."""
        info = inspect_table("public", "test_full")
        assert info is not None
        assert info.has_geom is True

        info = inspect_table("public", "test_gid")
        assert info is not None
        assert info.has_geom is True

    def test_has_geom_false(self, empty_table):
        """has_geom is False when geometry column is absent."""
        info = inspect_table("public", "test_no_geom")
        assert info is not None
        assert info.has_geom is False

    def test_special_columns_detected(self, full_table):
        """Presence of built_form_key, intersection_density, etc. is detected."""
        info = inspect_table("public", "test_full")
        assert info is not None
        assert info.has_built_form_key is True
        assert info.has_intersection_density is True
        assert info.has_land_development_category is True

    def test_missing_special_columns(self, gid_table):
        """Absence of special columns is correctly reported."""
        info = inspect_table("public", "test_gid")
        assert info is not None
        assert info.has_built_form_key is False
        assert info.has_intersection_density is False
        assert info.has_land_development_category is False
