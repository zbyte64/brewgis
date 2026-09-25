"""Tests for the layer registry."""

from __future__ import annotations

from itertools import pairwise
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.db import connection
from django.test import TestCase

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import _find_numeric_column
from brewgis.workspace.analysis.layer_registry import _get_geometry_type
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from tests.factories import LayerFactory
from tests.factories import StyleClassFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import WorkspaceFactory


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
        result = _find_numeric_column(columns, "some_table")
        self.assertEqual(result, "population")

    def test_falls_back_to_first_non_id_numeric_column(self) -> None:
        """Should return the first numeric column not in the skip set."""
        columns = [
            {"column_name": "id", "data_type": "integer", "numeric": True},
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "parcel_id", "data_type": "integer", "numeric": True},
            {"column_name": "some_value", "data_type": "numeric", "numeric": True},
        ]
        result = _find_numeric_column(columns, "some_table")
        self.assertEqual(result, "some_value")

    def test_returns_none_when_no_numeric_columns(self) -> None:
        """Should return None when all columns are non-numeric."""
        columns = [
            {"column_name": "geom", "data_type": "geometry", "numeric": False},
            {"column_name": "name", "data_type": "text", "numeric": False},
            {"column_name": "description", "data_type": "varchar", "numeric": False},
        ]
        result = _find_numeric_column(columns, "some_table")
        self.assertIsNone(result)

    def test_skips_preferred_column_if_not_numeric(self) -> None:
        """Should not return a preferred column name when it is non-numeric."""
        columns = [
            {"column_name": "population", "data_type": "text", "numeric": False},
            {"column_name": "total", "data_type": "integer", "numeric": True},
        ]
        result = _find_numeric_column(columns, "some_table")
        self.assertEqual(result, "total")

    def test_prefers_known_module_primary_column(self) -> None:
        """Should pick the module's headline output column over an incidental one."""
        columns = [
            {"column_name": "parcel_id", "data_type": "integer", "numeric": True},
            {
                "column_name": "area_gross_acres",
                "data_type": "numeric",
                "numeric": True,
            },
            {
                "column_name": "water_demand_total",
                "data_type": "numeric",
                "numeric": True,
            },
        ]
        result = _find_numeric_column(columns, "water_demand")
        self.assertEqual(result, "water_demand_total")

    def test_falls_back_when_primary_column_missing_from_table(self) -> None:
        """Should fall back to the generic heuristic if the primary column isn't present."""
        columns = [
            {"column_name": "parcel_id", "data_type": "integer", "numeric": True},
            {"column_name": "population", "data_type": "integer", "numeric": True},
        ]
        result = _find_numeric_column(columns, "water_demand")
        self.assertEqual(result, "population")


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
        mock_cursor_factory.return_value = self._mock_cursor(("geom", "MULTIPOLYGON"))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_for_polygon(self, mock_cursor_factory) -> None:
        """Polygon geometry should return 'fill'."""
        mock_cursor_factory.return_value = self._mock_cursor(("geom", "POLYGON"))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "fill")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_line_for_linestring(self, mock_cursor_factory) -> None:
        """Linestring geometry should return 'line'."""
        mock_cursor_factory.return_value = self._mock_cursor(("geom", "LINESTRING"))
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "line")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_line_for_multilinestring(self, mock_cursor_factory) -> None:
        """MultiLinestring geometry should return 'line'."""
        mock_cursor_factory.return_value = self._mock_cursor(
            ("geom", "MULTILINESTRING")
        )
        result = _get_geometry_type("public", "test_table")
        self.assertEqual(result, "line")

    @patch("brewgis.workspace.analysis.layer_registry.connection.cursor")
    def test_returns_fill_for_geometry_type_mismatch(self, mock_cursor_factory) -> None:
        """A generic catalog type (e.g. bare 'GEOMETRY', common for computed
        view columns) falls back to sampling a row's actual geometry via
        ST_GeometryType; when that's also unclassifiable, default to 'fill'."""
        mock_cursor = self._mock_cursor(("geom", "GEOMETRY"))
        mock_cursor.fetchone.side_effect = [
            ("geom", "GEOMETRY"),
            ("ST_GeometryCollection",),
        ]
        mock_cursor_factory.return_value = mock_cursor
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

    # A real result table: ``water_demand`` is a registered result table, so
    # it also exercises the registry's default palette for it.
    TABLE = "water_demand"

    # Shaped like a workspace's base canvas: a built form key per parcel.
    BASE_CANVAS_TABLE = "base_canvas_default_symbology"

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        # Every workspace has a BASE scenario in practice (created alongside
        # it) — auto_generate_symbology resolves one to decide whether to read
        # a layer's raw table or a scenario's paint overlay.
        Scenario.objects.create(
            name="Base Scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    def _create_result_table(self, scale: int = 1) -> None:
        """Create ``public.water_demand`` with 100 rows (values 1-100 × scale)."""
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {self.TABLE} CASCADE")
            cursor.execute(
                f"""
                CREATE TABLE {self.TABLE} (
                    parcel_id INTEGER,
                    water_demand_total DOUBLE PRECISION
                )
                """
            )
            cursor.execute(
                f"INSERT INTO {self.TABLE} (parcel_id, water_demand_total) "  # noqa: S608
                f"SELECT g, g * {scale} FROM generate_series(1, 100) AS g"
            )

    def tearDown(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {self.TABLE} CASCADE")
            cursor.execute(f"DROP TABLE IF EXISTS {self.BASE_CANVAS_TABLE} CASCADE")

    def _register(self) -> Layer:
        """Register :attr:`TABLE` for this test's workspace."""
        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table=self.TABLE,
        )
        assert layer is not None
        return layer

    def _create_base_canvas_table(self) -> None:
        """Create a base-canvas-shaped table: 60 parcels, 60 built form keys.

        The workspace's ``base_table`` points at it, because that is what the
        base-canvas layer's symbology is read from (``base_layer_source``).
        """
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {self.BASE_CANVAS_TABLE} CASCADE")
            cursor.execute(
                f"""
                CREATE TABLE {self.BASE_CANVAS_TABLE} (
                    parcel_id INTEGER,
                    built_form_key TEXT,
                    population DOUBLE PRECISION
                )
                """
            )
            cursor.execute(
                f"INSERT INTO {self.BASE_CANVAS_TABLE} "  # noqa: S608
                f"(parcel_id, built_form_key, population) "
                f"SELECT g, 'bf_' || g, g * 2 FROM generate_series(1, 60) AS g"
            )
        self.workspace.base_table = f"public.{self.BASE_CANVAS_TABLE}"
        self.workspace.save(update_fields=["base_table"])

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
    def test_creates_symbology_with_breaks_and_palette(
        self, mock_geom: MagicMock
    ) -> None:
        """Registering a result table should leave it with a real symbology:
        class breaks computed from the published values, the registry's
        palette for that table, and no leftover "Manual" palette."""
        mock_geom.return_value = "fill"
        self._create_result_table()

        layer = self._register()

        symbology = layer.symbology
        self.assertEqual(symbology.symbology_type, "graduated")
        self.assertEqual(symbology.attribute_column, "water_demand_total")
        self.assertEqual(symbology.num_classes, 5)
        self.assertEqual(symbology.palette_name, "blues")
        self.assertTrue(symbology.auto_generated)

        classes = list(symbology.classes.order_by("sort_order"))
        self.assertEqual(len(classes), 5)
        self.assertEqual(classes[0].min_value, 1.0)
        self.assertEqual(classes[-1].max_value, 100.0)
        # Each class carries a color sampled from the palette, and the breaks
        # are strictly increasing across the classes.
        self.assertTrue(all(c.color for c in classes))
        for previous, current in pairwise(classes):
            self.assertEqual(previous.max_value, current.min_value)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    def test_reregistration_refreshes_breaks(self, mock_geom: MagicMock) -> None:
        """A rerun publishes new values; re-registering the layer must
        recompute the breaks instead of leaving the previous run's."""
        mock_geom.return_value = "fill"
        self._create_result_table()
        layer = self._register()
        first_breaks = [
            c.max_value for c in layer.symbology.classes.order_by("sort_order")
        ]
        self.assertEqual(first_breaks[-1], 100.0)

        # The rerun published values 100× larger.
        self._create_result_table(scale=100)
        layer = self._register()

        classes = list(layer.symbology.classes.order_by("sort_order"))
        self.assertEqual(classes[0].min_value, 100.0)
        self.assertEqual(classes[-1].max_value, 10_000.0)
        self.assertNotEqual(
            [c.max_value for c in classes],
            first_breaks,
        )

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    def test_base_canvas_defaults_to_built_form_key_in_glasbey(
        self, mock_geom: MagicMock
    ) -> None:
        """The base canvas layer draws ``built_form_key``, not a numeric column.

        Every key gets its own class *and* its own color: 60 keys is past the
        10-color categorical palettes, so the default has to be the large one.
        """
        mock_geom.return_value = "fill"
        self._create_base_canvas_table()

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table=self.BASE_CANVAS_TABLE,
            key=BASE_CANVAS_LAYER_KEY,
            name="Base Canvas",
        )

        self.assertIsNotNone(layer)
        symbology = layer.symbology
        self.assertEqual(symbology.symbology_type, "categorical")
        self.assertEqual(symbology.attribute_column, "built_form_key")
        self.assertEqual(symbology.palette_name, "glasbey")

        classes = list(symbology.classes.order_by("sort_order"))
        self.assertEqual(len(classes), 60)
        self.assertEqual({c.label for c in classes}, {f"bf_{g}" for g in range(1, 61)})
        self.assertEqual(len({c.color for c in classes}), 60)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    def test_base_canvas_falls_back_to_a_numeric_column(
        self, mock_geom: MagicMock
    ) -> None:
        """A base canvas without a built form key column keeps the generic rule."""
        mock_geom.return_value = "fill"
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {self.BASE_CANVAS_TABLE} CASCADE")
            cursor.execute(
                f"""
                CREATE TABLE {self.BASE_CANVAS_TABLE} (
                    parcel_id INTEGER,
                    population DOUBLE PRECISION
                )
                """
            )
            cursor.execute(
                f"INSERT INTO {self.BASE_CANVAS_TABLE} (parcel_id, population) "  # noqa: S608
                f"SELECT g, g FROM generate_series(1, 100) AS g"
            )
        self.workspace.base_table = f"public.{self.BASE_CANVAS_TABLE}"
        self.workspace.save(update_fields=["base_table"])

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table=self.BASE_CANVAS_TABLE,
            key=BASE_CANVAS_LAYER_KEY,
        )

        self.assertEqual(layer.symbology.attribute_column, "population")
        self.assertEqual(layer.symbology.symbology_type, "graduated")

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
    def test_update_backfills_symbology_when_layer_has_none(
        self, mock_geom: MagicMock
    ) -> None:
        """Updating a Layer with no existing SymbologyConfig should backfill
        one — a Layer first registered before its table existed (so no
        numeric column was found) gets symbology once the table shows up."""
        mock_geom.return_value = "fill"
        self._create_result_table()

        # First registration: the table isn't there yet, so there is nothing
        # to classify and no config is written.
        with patch(
            "brewgis.workspace.analysis.layer_registry._get_table_columns",
            return_value=[],
        ):
            layer = self._register()
        with self.assertRaises(Layer.symbology.RelatedObjectDoesNotExist):
            layer.symbology

        layer = self._register()

        self.assertEqual(layer.symbology.attribute_column, "water_demand_total")
        self.assertEqual(layer.symbology.palette_name, "blues")
        self.assertTrue(layer.symbology.auto_generated)

    @patch("brewgis.workspace.analysis.layer_registry._get_geometry_type")
    @patch("brewgis.workspace.analysis.layer_registry._get_table_columns")
    def test_update_does_not_overwrite_customized_symbology(
        self, mock_columns: MagicMock, mock_geom: MagicMock
    ) -> None:
        """A user-customized SymbologyConfig (auto_generated=False) must be
        left untouched when the Layer it belongs to is re-registered."""
        mock_geom.return_value = "fill"
        mock_columns.return_value = [
            {"column_name": "population", "data_type": "integer", "numeric": True},
        ]

        existing = LayerFactory(
            workspace=self.workspace,
            key="existing_customized",
            db_table="existing_customized",
        )
        config = SymbologyConfigFactory(
            layer=existing,
            symbology_type="categorical",
            attribute_column="my_custom_column",
            auto_generated=False,
        )
        StyleClassFactory(
            symbology=config, label="custom", color="#123456", sort_order=0
        )

        layer = register_result_layer(
            workspace_id=self.workspace.pk,
            schema="public",
            table="existing_customized",
        )

        self.assertIsNotNone(layer)
        self.assertEqual(layer.symbology.attribute_column, "my_custom_column")
        self.assertEqual(layer.symbology.symbology_type, "categorical")
        self.assertFalse(layer.symbology.auto_generated)
        self.assertEqual([c.label for c in layer.symbology.classes.all()], ["custom"])
