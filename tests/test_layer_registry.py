"""Tests for the layer registry."""
# ruff: noqa: ANN001, ANN201

from __future__ import annotations

import pytest

from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase
from tests.factories import LayerFactory
from tests.factories import WorkspaceFactory
from brewgis.workspace.models import Layer

from brewgis.workspace.analysis.layer_registry import (
    _find_numeric_column,
    _get_geometry_type,
    register_result_layer,
)


@pytest.mark.integration
class TestFindNumericColumn(TestCase):
    """Tests for _find_numeric_column."""

    def test_returns_preferred_column_when_present(self) -> None:
        """Should return 'population' when it appears among mixed columns."""
        columns = [
            {"column_name": "id", "data_type": "integer", "numeric": True},
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "population", "data_type": "integer", "numeric": True},
            {"column_name": "label", "data_type": "text", "numeric": False},
        ]
        result = _find_numeric_column(columns)
        self.assertEqual(result, "population")

    def test_falls_back_to_first_non_id_numeric_column(self) -> None:
        """Should return the first numeric column not in the skip set."""
        columns = [
            {"column_name": "id", "data_type": "integer", "numeric": True},
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "parcel_id", "data_type": "integer", "numeric": True},
            {"column_name": "some_value", "data_type": "numeric", "numeric": True},
        ]
        result = _find_numeric_column(columns)
        self.assertEqual(result, "some_value")

    def test_returns_none_when_no_numeric_columns(self) -> None:
        """Should return None when all columns are non-numeric."""
        columns = [
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "name", "data_type": "text", "numeric": False},
            {"column_name": "description", "data_type": "varchar", "numeric": False},
        ]
        result = _find_numeric_column(columns)
        self.assertIsNone(result)

    def test_skips_preferred_column_if_not_numeric(self) -> None:
        """Should not return a preferred column name when it is non-numeric."""
        columns = [
            {"column_name": "population", "data_type": "text", "numeric": False},
            {"column_name": "total", "data_type": "integer", "numeric": True},
        ]
        result = _find_numeric_column(columns)
        self.assertEqual(result, "total")


@pytest.mark.integration
class TestGetGeometryType(TestCase):
    """Tests for _get_geometry_type."""

    def _mock_cursor(self, fetchone_result):
        """Build a mock cursor context manager."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_result
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = None
        return mock_cursor

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_for_multipolygon(self, mock_cursor_factory) -> None:
        """Multipolygon geometry should return 'fill'."""
        mock_cursor_factory.return_value = self._mock_cursor(("MULTIPOLYGON",))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_for_polygon(self, mock_cursor_factory) -> None:
        """Polygon geometry should return 'fill'."""
        mock_cursor_factory.return_value = self._mock_cursor(("POLYGON",))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_line_for_linestring(self, mock_cursor_factory) -> None:
        """Linestring geometry should return 'line'."""
        mock_cursor_factory.return_value = self._mock_cursor(("LINESTRING",))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "line")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_line_for_multilinestring(self, mock_cursor_factory) -> None:
        """MultiLinestring geometry should return 'line'."""
        mock_cursor_factory.return_value = self._mock_cursor(("MULTILINESTRING",))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "line")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_for_geometry_type_mismatch(self, mock_cursor_factory) -> None:
        """Unhandled geometry type (e.g. POINT) should default to 'fill'."""
        mock_cursor_factory.return_value = self._mock_cursor(("POINT",))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_when_no_geometry_row(self, mock_cursor_factory) -> None:
        """Missing geometry_columns entry should default to 'fill'."""
        mock_cursor_factory.return_value = self._mock_cursor(None)
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")


@pytest.mark.integration
class TestRegisterResultLayer(TestCase):
    """Tests for register_result_layer."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_creates_new_layer(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """A new Layer should be created when no matching key exists."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = [
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
        ]

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="new_result_view",
        )

        self.assertIsNotNone(layer)
        self.assertEqual(layer.key, "new_result_view")
        self.assertEqual(layer.name, "New Result View")
        self.assertEqual(layer.geometry_type, "fill")
        self.assertEqual(layer.layer_source, "postgis")
        self.assertEqual(layer.db_table, "new_result_view")
        self.assertEqual(layer.workspace.pk, self.workspace.pk)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_creates_new_layer_with_custom_name(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """A custom name should be used when provided."""
        mock_geom.return_value = "line"
        mock_columns.return_value = []

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="custom_name_view",
            name="My Custom Layer",
        )

        self.assertIsNotNone(layer)
        self.assertEqual(layer.name, "My Custom Layer")

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_updates_existing_layer(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """An existing Layer with the same key should be updated."""
        mock_geom.return_value = "line"
        mock_columns.return_value = []

        existing = LayerFactory(
            workspace=self.workspace,
            key="existing_view",
            name="Old Name",
            geometry_type="fill",
        )

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="existing_view",
            name="Updated Name",
        )

        self.assertIsNotNone(layer)
        self.assertEqual(layer.pk, existing.pk)
        self.assertEqual(layer.name, "Updated Name")
        self.assertEqual(layer.geometry_type, "line")

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_update_preserves_description(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """Custom description should be persisted on update."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = []

        LayerFactory(
            workspace=self.workspace,
            key="desc_view",
            name="Original",
        )

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="desc_view",
            description="Custom description",
        )

        self.assertIsNotNone(layer)
        self.assertEqual(layer.description, "Custom description")

    def test_returns_none_when_workspace_not_found(self) -> None:
        """Non-existent workspace ID should return None."""
        result = register_result_layer(
            workspace_id=999_999,
            schema="public",
            table="orphan_view",
        )
        self.assertIsNone(result)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_creates_symbology_for_new_layer_with_numeric_column(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """A graduated SymbologyConfig should be auto-created when a numeric column exists."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = [
            {"column_name": "id", "data_type": "integer", "numeric": True},
            {"column_name": "population", "data_type": "bigint", "numeric": True},
        ]

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="auto_symbology_view",
        )

        self.assertIsNotNone(layer)
        symbology = layer.symbology
        self.assertIsNotNone(symbology)
        self.assertEqual(symbology.symbology_type, "graduated")
        self.assertEqual(symbology.attribute_column, "population")
        self.assertEqual(symbology.num_classes, 5)
        self.assertTrue(symbology.auto_generated)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_does_not_create_symbology_when_no_numeric_column(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """SymbologyConfig should not be created when no numeric column is found."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = [
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "name", "data_type": "text", "numeric": False},
        ]

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="no_numeric_view",
        )

        self.assertIsNotNone(layer)
        with self.assertRaises(Layer.symbology.RelatedObjectDoesNotExist):
            layer.symbology

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_update_does_not_create_symbology(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """SymbologyConfig should not be auto-created when updating an existing Layer."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = [
            {"column_name": "population", "data_type": "integer", "numeric": True},
        ]

        LayerFactory(
            workspace=self.workspace,
            key="existing_no_sym",
            db_table="existing_no_sym",
        )

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="existing_no_sym",
        )

        self.assertIsNotNone(layer)
        with self.assertRaises(Layer.symbology.RelatedObjectDoesNotExist):
            layer.symbology
