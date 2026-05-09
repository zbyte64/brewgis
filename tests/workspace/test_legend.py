"""Tests for the legend generation service."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.workspace.symbology.legend import SymbologyLegend
from brewgis.workspace.symbology.legend import generate_legend
from tests.factories import LayerFactory
from tests.factories import StyleClassFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import WorkspaceFactory


@pytest.mark.models
class TestGenerateLegend(TestCase):
    """Tests for :func:`generate_legend`."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()

    def test_single_symbol_legend(self) -> None:
        """Single symbol config produces exactly one item with defaults."""
        layer = LayerFactory(workspace=self.workspace, name="Test Layer")
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            default_color="#ff0000",
            default_opacity=0.8,
            null_handling="hide",
        )
        legend = generate_legend(config)

        assert isinstance(legend, SymbologyLegend)
        assert legend.layer_name == "Test Layer"
        assert legend.symbology_type == "single"
        assert len(legend.items) == 1
        assert legend.items[0].label == "Test Layer"
        assert legend.items[0].color == "#ff0000"
        assert legend.items[0].opacity == 0.8
        assert legend.items[0].type_hint == "fill"
        assert not legend.items[0].is_null_item
        assert legend.items[0].min_value is None
        assert legend.items[0].max_value is None
        assert legend.null_info is None

    def test_categorical_legend(self) -> None:
        """Categorical config produces one item per StyleClass, ordered by sort_order."""
        layer = LayerFactory(workspace=self.workspace, name="Categorical Layer")
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="categorical",
        )
        StyleClassFactory(symbology=config, label="High", color="#ff0000", sort_order=1)
        StyleClassFactory(
            symbology=config, label="Medium", color="#ffff00", sort_order=0
        )
        StyleClassFactory(symbology=config, label="Low", color="#00ff00", sort_order=2)

        legend = generate_legend(config)

        items = legend.items[:3]  # exclude potential null item
        assert len(items) == 3
        assert items[0].label == "Medium"
        assert items[0].color == "#ffff00"
        assert items[1].label == "High"
        assert items[1].color == "#ff0000"
        assert items[2].label == "Low"
        assert items[2].color == "#00ff00"

    def test_graduated_legend_with_ranges(self) -> None:
        """Graduated config populates min/max and auto-generates labels."""
        layer = LayerFactory(workspace=self.workspace, name="Graduated Layer")
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="graduated",
        )
        StyleClassFactory(
            symbology=config,
            label="",  # blank — should auto-generate
            min_value=0.0,
            max_value=50.0,
            color="#4400ff",
            sort_order=0,
        )
        StyleClassFactory(
            symbology=config,
            label="",  # blank — should auto-generate
            min_value=50.0,
            max_value=100.0,
            color="#ff0044",
            sort_order=1,
        )

        legend = generate_legend(config)

        items = legend.items[:2]
        assert len(items) == 2
        assert items[0].min_value == 0.0
        assert items[0].max_value == 50.0
        assert items[0].label == "0.00 — 50.00"
        assert items[0].color == "#4400ff"
        assert items[1].min_value == 50.0
        assert items[1].max_value == 100.0
        assert items[1].label == "50.00 — 100.00"
        assert items[1].color == "#ff0044"

    def test_null_handling_gray(self) -> None:
        """null_handling='gray' appends a null item with gray color and 'No Data' label."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            null_handling="gray",
            null_color="#cccccc",
        )
        legend = generate_legend(config)

        assert legend.null_info is not None
        assert legend.null_info.null_handling == "gray"
        assert legend.null_info.null_color == "#cccccc"

        null_item = legend.items[-1]
        assert null_item.is_null_item
        assert null_item.label == "No Data"
        assert null_item.color == "#cccccc"

    def test_null_handling_custom_color(self) -> None:
        """null_handling='custom_color' uses the configured null_color."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            null_handling="custom_color",
            null_color="#ff00ff",
        )
        legend = generate_legend(config)

        assert legend.null_info is not None
        assert legend.null_info.null_handling == "custom_color"
        assert legend.null_info.null_color == "#ff00ff"

        null_item = legend.items[-1]
        assert null_item.is_null_item
        assert null_item.color == "#ff00ff"

    def test_null_handling_hide(self) -> None:
        """null_handling='hide' does NOT append a null item."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            null_handling="hide",
        )
        legend = generate_legend(config)

        assert not any(item.is_null_item for item in legend.items)
        # null_info may be None if zero_transparent is also False
        if legend.null_info is not None:
            assert legend.null_info.null_handling == "hide"

    def test_zero_transparent_info(self) -> None:
        """zero_transparent=True sets the flag on null_info."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            null_handling="gray",
            zero_transparent=True,
        )
        legend = generate_legend(config)

        assert legend.null_info is not None
        assert legend.null_info.zero_transparent is True

    def test_geometry_type_hint(self) -> None:
        """Geometry type is reflected in each LegendItem's type_hint."""
        layer = LayerFactory(workspace=self.workspace, geometry_type="line")
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
        )
        legend = generate_legend(config)

        for item in legend.items:
            assert item.type_hint == "line", f"Expected 'line', got '{item.type_hint}'"

    def test_empty_classes_does_not_crash(self) -> None:
        """A config with no StyleClasses does not crash and returns empty items (excluding null)."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="graduated",
        )
        # No StyleClasses created
        legend = generate_legend(config)

        # Items should be empty except for any null item
        non_null_items = [i for i in legend.items if not i.is_null_item]
        assert len(non_null_items) == 0

    def test_blank_label_on_style_class(self) -> None:
        """A blank label on a StyleClass auto-generates from class index."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="categorical",
        )
        StyleClassFactory(symbology=config, label="", sort_order=0)
        StyleClassFactory(symbology=config, label="", sort_order=1)
        StyleClassFactory(symbology=config, label="Custom", sort_order=2)

        legend = generate_legend(config)

        non_null = [i for i in legend.items if not i.is_null_item]
        assert non_null[0].label == "Class 1"
        assert non_null[1].label == "Class 2"
        assert non_null[2].label == "Custom"

    def test_null_handling_blank_defaults_to_gray(self) -> None:
        """A blank null_handling field is treated as 'gray'."""
        layer = LayerFactory(workspace=self.workspace)
        config = SymbologyConfigFactory(
            layer=layer,
            symbology_type="single",
            null_handling="",
            null_color="",
        )
        legend = generate_legend(config)

        assert legend.null_info is not None
        assert legend.null_info.null_handling == "gray"
        assert legend.null_info.null_color == "#cccccc"

        null_item = legend.items[-1]
        assert null_item.is_null_item
        assert null_item.color == "#cccccc"
