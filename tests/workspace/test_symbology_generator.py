"""Unit tests for the MapLibre style generator (brewgis.workspace.symbology.generator)."""

from __future__ import annotations

from brewgis.workspace.models import Layer
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.symbology.generator import generate_maplibre_style


def _graduated_config(**overrides: object) -> SymbologyConfig:
    layer = Layer(geometry_type="fill")
    defaults: dict[str, object] = {
        "layer": layer,
        "symbology_type": "graduated",
        "attribute_column": "vmt_total",
        "default_color": "#888888",
        "null_handling": "gray",
    }
    defaults.update(overrides)
    return SymbologyConfig(**defaults)


def _class(config: SymbologyConfig, **overrides: object) -> StyleClass:
    defaults: dict[str, object] = {
        "symbology": config,
        "label": "0 - 10",
        "color": "#ff0000",
        "min_value": 0,
    }
    defaults.update(overrides)
    return StyleClass(**defaults)


def _step_expression(paint: dict[str, object]) -> list:
    """Unwrap the null-handling ``case`` wrapper to get at the inner expression."""
    fill_color = paint["fill-color"]
    assert fill_color[0] == "case"
    return fill_color[2]


class TestGraduatedPaintDegenerateClasses:
    """A quantile classification can collapse to very few classes when the
    underlying data is mostly one value (e.g. VMT is 0 for most parcels) —
    the generated MapLibre expression must stay valid in that case."""

    def test_single_class_falls_back_to_flat_color_not_a_step_expression(self) -> None:
        config = _graduated_config()
        classes = [_class(config, color="#ffcc00")]

        style = generate_maplibre_style(config, classes=classes)

        inner = _step_expression(style["paint"])
        assert inner == "#ffcc00"

    def test_zero_classes_falls_back_to_single_paint(self) -> None:
        config = _graduated_config()

        style = generate_maplibre_style(config, classes=[])

        assert style["paint"]["fill-color"] == config.default_color

    def test_two_or_more_classes_produce_a_valid_step_expression(self) -> None:
        config = _graduated_config()
        classes = [
            _class(config, color="#ffcc00", min_value=0),
            _class(config, color="#ff0000", min_value=10),
        ]

        style = generate_maplibre_style(config, classes=classes)

        inner = _step_expression(style["paint"])
        assert inner[0] == "step"
        # operator + input + base color + (threshold, color) pair == 5 elements.
        assert len(inner) >= 5
        assert inner[2] == "#ffcc00"
        assert inner[3] == 10
        assert inner[4] == "#ff0000"
