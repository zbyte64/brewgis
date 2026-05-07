"""Tests for the MapLibre GL style JSON generator."""

from __future__ import annotations

from django.test import TestCase

from brewgis.workspace.models import Layer
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.symbology.generator import generate_maplibre_style


class TestGenerator(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Test Workspace",
            db_schema="public",
        )
        self.layer = Layer.objects.create(
            key="test-layer",
            name="Test Layer",
            workspace=self.workspace,
            db_table="test_table",
            layer_source="test",
            geometry_type="fill",
        )

    def _make_config(
        self,
        symbology_type: str = "single",
        **kwargs: object,
    ) -> SymbologyConfig:
        defaults: dict[str, object] = {
            "layer": self.layer,
            "symbology_type": symbology_type,
            "attribute_column": "",
            "default_color": "#888888",
            "default_opacity": 0.7,
            "stroke_color": "",
            "stroke_width": 1.0,
            "line_width": 1.0,
            "circle_radius": 4.0,
            "palette_name": "",
            "reverse_palette": False,
            "num_classes": 5,
            "classification_method": "quantile",
            "null_handling": "gray",
            "null_color": "",
            "zero_transparent": False,
            "auto_generated": True,
        }
        defaults.update(kwargs)
        return SymbologyConfig.objects.create(**defaults)

    def test_single_fill(self) -> None:
        """Single-symbol fill should produce flat paint properties."""
        config = self._make_config(
            symbology_type="single",
            default_color="#ff0000",
            default_opacity=0.5,
        )
        result = generate_maplibre_style(config)
        assert "paint" in result
        assert "layout" in result
        assert result["paint"]["fill-color"] == "#ff0000"
        assert result["paint"]["fill-opacity"] == 0.5

    def test_single_line(self) -> None:
        """Single-symbol line geometry."""
        self.layer.geometry_type = "line"
        self.layer.save()
        config = self._make_config(
            symbology_type="single",
            default_color="#00ff00",
            line_width=2.5,
        )
        result = generate_maplibre_style(config)
        assert result["paint"]["line-color"] == "#00ff00"
        assert result["paint"]["line-width"] == 2.5

    def test_single_circle(self) -> None:
        """Single-symbol point geometry."""
        self.layer.geometry_type = "circle"
        self.layer.save()
        config = self._make_config(
            symbology_type="single",
            default_color="#0000ff",
            circle_radius=6.0,
        )
        result = generate_maplibre_style(config)
        assert result["paint"]["circle-color"] == "#0000ff"
        assert result["paint"]["circle-radius"] == 6.0

    def test_categorical_match_expression(self) -> None:
        """Categorical symbology should produce a match expression."""
        config = self._make_config(
            symbology_type="categorical",
            attribute_column="category",
        )
        StyleClass.objects.create(
            symbology=config,
            label="A",
            color="#ff0000",
            sort_order=0,
        )
        StyleClass.objects.create(
            symbology=config,
            label="B",
            color="#00ff00",
            sort_order=1,
        )
        result = generate_maplibre_style(config)
        paint = result["paint"]
        expr = paint["fill-color"]
        # Should be a case or match expression
        assert isinstance(expr, list)
        # Should contain ["match", ["get", "category"], ...]
        assert "match" in str(expr)

    def test_graduated_step_expression(self) -> None:
        """Graduated symbology should produce a step expression."""
        config = self._make_config(
            symbology_type="graduated",
            attribute_column="population",
        )
        StyleClass.objects.create(
            symbology=config,
            label="Low",
            color="#ffffcc",
            min_value=0.0,
            max_value=100.0,
            sort_order=0,
        )
        StyleClass.objects.create(
            symbology=config,
            label="Mid",
            color="#fd8d3c",
            min_value=100.0,
            max_value=500.0,
            sort_order=1,
        )
        StyleClass.objects.create(
            symbology=config,
            label="High",
            color="#800026",
            min_value=500.0,
            max_value=1000.0,
            sort_order=2,
        )
        result = generate_maplibre_style(config)
        paint = result["paint"]
        expr = paint["fill-color"]
        assert isinstance(expr, list)
        # Should contain ["step", ["get", "population"], ...]
        assert "step" in str(expr)

    def test_zero_transparent(self) -> None:
        """Zero-transparent flag should wrap opacity in a case expression."""
        config = self._make_config(
            symbology_type="single",
            attribute_column="value",
            zero_transparent=True,
        )
        result = generate_maplibre_style(config)
        assert isinstance(result["paint"]["fill-opacity"], list)
        assert "case" in str(result["paint"]["fill-opacity"])

    def test_null_hide(self) -> None:
        """Null handling 'hide' should produce a case expression."""
        config = self._make_config(
            symbology_type="categorical",
            attribute_column="cat",
            null_handling="hide",
        )
        StyleClass.objects.create(
            symbology=config,
            label="X",
            color="#ff0000",
            sort_order=0,
        )
        result = generate_maplibre_style(config)
        expr = result["paint"]["fill-color"]
        assert isinstance(expr, list)
        # Should wrap in ["case", ["has", "cat"], ...]
        assert "has" in str(expr)
