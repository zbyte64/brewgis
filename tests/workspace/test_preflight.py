# ruff: noqa: ANN201, ARG002
"""Tests for the preflight validation service."""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.services.preflight import check_analysis_prerequisites


@pytest.fixture
def parcel_table(db) -> str:
    """Create a valid parcel table with id, geom, and built_form_key."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_preflight_parcel (
                id SERIAL PRIMARY KEY,
                built_form_key INTEGER DEFAULT 2,
                geom GEOMETRY(POLYGON, 4326)
            )
            """
        )
    yield "public.test_preflight_parcel"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_preflight_parcel CASCADE")


@pytest.fixture
def built_forms_table(db) -> str:
    """Create a built_forms table with data."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_preflight_bt (
                id SERIAL PRIMARY KEY,
                name VARCHAR(64)
            )
            """
        )
        cursor.execute(
            "INSERT INTO test_preflight_bt (name) VALUES ('SFR Standard')"
        )
    yield "public.test_preflight_bt"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_preflight_bt CASCADE")


@pytest.fixture
def base_canvas_table(db) -> str:
    """Create a base canvas table stub."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_preflight_bc (
                parcel_id INTEGER PRIMARY KEY,
                population FLOAT DEFAULT 0.0
            )
            """
        )
    yield "public.test_preflight_bc"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_preflight_bc CASCADE")


@pytest.mark.integration
class TestCheckAnalysisPrerequisites:
    """Tests for :func:`check_analysis_prerequisites`."""

    def test_all_checks_pass(
        self, parcel_table, built_forms_table, base_canvas_table
    ):
        """When all prerequisites are met, returns empty list."""
        errors = check_analysis_prerequisites(
            schema="public",
            parcel_table="test_preflight_parcel",
            built_form_table="test_preflight_bt",
            base_canvas_table="test_preflight_bc",
        )
        assert errors == []

    def test_parcel_table_missing(self, db):
        """Missing parcel table returns an error."""
        errors = check_analysis_prerequisites(
            schema="public",
            parcel_table="table_does_not_exist",
            built_form_table=None,
            base_canvas_table=None,
        )
        assert len(errors) == 1
        assert errors[0].field == "parcel_table"
        assert "not found" in errors[0].message.lower()

    def test_parcel_table_no_geom(self, db):
        """Parcel table without geometry column returns an error."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS test_no_geom_pre (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(64)
                )
                """
            )
        try:
            errors = check_analysis_prerequisites(
                schema="public",
                parcel_table="test_no_geom_pre",
                built_form_table=None,
                base_canvas_table=None,
            )
            assert len(errors) >= 1
            geom_errors = [e for e in errors if "geometry" in e.message.lower()]
            assert len(geom_errors) >= 1
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS test_no_geom_pre CASCADE")

    def test_built_forms_table_missing(self, parcel_table):
        """Missing built_forms table returns an error."""
        errors = check_analysis_prerequisites(
            schema="public",
            parcel_table="test_preflight_parcel",
            built_form_table="bt_does_not_exist",
        )
        assert any("built form" in e.message.lower() for e in errors)

    def test_built_forms_table_empty(self, parcel_table, built_forms_table, db):
        """Empty built_forms table returns an error."""
        # Create an empty table
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS test_empty_bt (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(64)
                )
                """
            )
        try:
            errors = check_analysis_prerequisites(
                schema="public",
                parcel_table="test_preflight_parcel",
                built_form_table="test_empty_bt",
            )
            assert any("empty" in e.message.lower() for e in errors)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS test_empty_bt CASCADE")

    def test_base_canvas_missing(self, parcel_table, built_forms_table):
        """Missing base canvas returns an error."""
        errors = check_analysis_prerequisites(
            schema="public",
            parcel_table="test_preflight_parcel",
            built_form_table="test_preflight_bt",
            base_canvas_table="bc_does_not_exist",
        )
        assert any("base canvas" in e.message.lower() for e in errors)

    def test_field_values_in_error(self, parcel_table):
        """Error message includes the table name that failed."""
        errors = check_analysis_prerequisites(
            schema="public",
            parcel_table="test_preflight_parcel",
            built_form_table="missing_bt_table",
        )
        assert any("missing_bt_table" in e.message for e in errors)
