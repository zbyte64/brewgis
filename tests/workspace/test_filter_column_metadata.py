# ruff: noqa: ANN201
"""Tests for filter.py's _column_metadata — field choices fed to <filter-builder>."""

from __future__ import annotations

import pytest
from django.db import connection
from django.shortcuts import reverse
from django.test import TestCase

from brewgis.workspace.views.filter import _column_metadata
from tests.factories import LayerFactory
from tests.factories import UserFactory


@pytest.fixture
def mixed_column_table(db) -> str:
    """A table with numeric, text, and geometry columns."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS test_filter_columns (
                existing_du FLOAT,
                land_use VARCHAR(64),
                geometry GEOMETRY(POLYGON, 4326)
            )
            """
        )
    yield "test_filter_columns"
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS test_filter_columns CASCADE")


@pytest.mark.django_db
def test_column_metadata_excludes_geometry_and_flags_numeric(mixed_column_table):
    layer = LayerFactory(db_table=mixed_column_table)
    columns = _column_metadata(layer)

    names = {c["name"] for c in columns}
    assert names == {"existing_du", "land_use"}
    by_name = {c["name"]: c["numeric"] for c in columns}
    assert by_name["existing_du"] is True
    assert by_name["land_use"] is False


@pytest.mark.django_db
def test_column_metadata_empty_for_nonexistent_table():
    layer = LayerFactory(db_table="does_not_exist_anywhere")
    assert _column_metadata(layer) == []


@pytest.mark.views
class TestFilterEditorRendersColumns(TestCase):
    """The editor view should feed <filter-builder> real column metadata."""

    def test_editor_includes_filter_builder_with_columns(self):
        # TestCase wraps each test in a transaction that's rolled back
        # afterward, so this table never outlives the test.
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS test_filter_editor_cols "
                "(existing_du FLOAT, land_use VARCHAR(64))"
            )
        user = UserFactory()
        self.client.force_login(user)
        layer = LayerFactory(db_table="test_filter_editor_cols")

        url = reverse("workspace:layer_filter_create", kwargs={"layer_pk": layer.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<filter-builder")
        self.assertContains(response, "existing_du")
        self.assertContains(response, "land_use")
