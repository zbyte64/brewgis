"""MapLibre GL style JSON generator for BrewGIS symbology.

Transforms a ``SymbologyConfig`` (and its ``StyleClass`` children) into
MapLibre GL ``paint`` and ``layout`` dictionaries suitable for merging
into the layer configuration consumed by ``<brew-gis-map>``.
"""

from __future__ import annotations

from typing import Any

import deal

from brewgis.workspace.models import SymbologyConfig


def _null_expression(
    symbology: SymbologyConfig,
    inner: list[Any],
) -> list[Any]:
    """Wrap *inner* in a ``case`` expression that handles nulls."""
    null_handling = symbology.null_handling
    attr = symbology.attribute_column

    if null_handling == "hide":
        # Use a case expression to filter out nulls
        return ["case", ["has", attr], inner, ["literal", {"visibility": "none"}]]

    null_color = symbology.null_color or "#cccccc"
    return ["case", ["has", attr], inner, null_color]


@deal.has()
def _base_paint(symbology: SymbologyConfig) -> dict[str, Any]:
    """Return base paint properties common to all symbology types."""
    geo = symbology.layer.geometry_type
    paint: dict[str, Any] = {}

    if geo == "fill":
        paint["fill-color"] = symbology.default_color
        paint["fill-opacity"] = symbology.default_opacity
        if symbology.stroke_color:
            paint["fill-outline-color"] = symbology.stroke_color
    elif geo == "line":
        paint["line-color"] = symbology.default_color
        paint["line-opacity"] = symbology.default_opacity
        paint["line-width"] = symbology.line_width
    elif geo == "circle":
        paint["circle-color"] = symbology.default_color
        paint["circle-opacity"] = symbology.default_opacity
        paint["circle-radius"] = symbology.circle_radius

    return paint


def _base_layout(symbology: SymbologyConfig) -> dict[str, Any]:
    """Return base layout properties."""
    geo = symbology.layer.geometry_type
    layout: dict[str, Any] = {}

    if geo == "fill":
        layout["visibility"] = "visible"
    return layout


def _categorical_paint(symbology: SymbologyConfig) -> dict[str, Any]:
    """Generate a ``match`` paint expression for categorical symbology."""
    attr = symbology.attribute_column
    classes = list(symbology.classes.all().order_by("sort_order"))
    geo = symbology.layer.geometry_type

    color_key = {
        "fill": "fill-color",
        "line": "line-color",
        "circle": "circle-color",
    }[geo]

    # Build match expression: ["match", ["get", attr], val1, color1, val2, color2, ..., default]
    match_parts: list[Any] = ["match", ["get", attr]]
    for sc in classes:
        match_parts.append(sc.label)
        match_parts.append(sc.color or symbology.default_color)
    match_parts.append(symbology.default_color)

    return {color_key: _null_expression(symbology, match_parts)}


def _graduated_paint(symbology: SymbologyConfig) -> dict[str, Any]:
    """Generate a ``step`` paint expression for graduated symbology."""
    attr = symbology.attribute_column
    classes = list(symbology.classes.all().order_by("sort_order"))
    geo = symbology.layer.geometry_type

    color_key = {
        "fill": "fill-color",
        "line": "line-color",
        "circle": "circle-color",
    }[geo]

    # Build step expression: ["step", ["get", attr], color_below_first, threshold1, color1, ...]
    step_parts: list[Any] = ["step", ["get", attr]]

    # Default color (below first threshold)
    if classes:
        step_parts.append(classes[0].color or symbology.default_color)
        for sc in classes[1:]:
            step_parts.append(sc.min_value or 0)
            step_parts.append(sc.color or symbology.default_color)
    else:
        step_parts.append(symbology.default_color)

    return {color_key: _null_expression(symbology, step_parts)}


def _single_paint(symbology: SymbologyConfig) -> dict[str, Any]:
    """Generate simple flat paint properties for single-symbol symbology."""
    geo = symbology.layer.geometry_type
    paint: dict[str, Any] = {}

    if geo == "fill":
        paint["fill-color"] = symbology.default_color
        paint["fill-opacity"] = symbology.default_opacity
        if symbology.stroke_color:
            paint["fill-outline-color"] = symbology.stroke_color
    elif geo == "line":
        paint["line-color"] = symbology.default_color
        paint["line-opacity"] = symbology.default_opacity
        paint["line-width"] = symbology.line_width
    elif geo == "circle":
        paint["circle-color"] = symbology.default_color
        paint["circle-opacity"] = symbology.default_opacity
        paint["circle-radius"] = symbology.circle_radius

    return paint


@deal.post(lambda result: "paint" in result and "layout" in result)
def generate_maplibre_style(symbology: SymbologyConfig) -> dict[str, Any]:
    """Generate MapLibre GL ``paint`` and ``layout`` for a symbology config.

    Returns
    -------
    dict
        With keys ``"paint"`` and ``"layout"``, suitable for merging into
        a layer dict passed to ``<brew-gis-map>``.
    """
    stype = symbology.symbology_type

    if stype == "single":
        paint = _single_paint(symbology)
    elif stype == "categorical":
        paint = _categorical_paint(symbology)
    elif stype == "graduated":
        paint = _graduated_paint(symbology)
    else:
        paint = _base_paint(symbology)

    layout = _base_layout(symbology)

    # Zero-transparent handling
    if symbology.zero_transparent and symbology.attribute_column:
        geo = symbology.layer.geometry_type
        opacity_key = {
            "fill": "fill-opacity",
            "line": "line-opacity",
            "circle": "circle-opacity",
        }[geo]
        paint[opacity_key] = [
            "case",
            ["==", ["get", symbology.attribute_column], 0],
            0,
            paint.get(opacity_key, symbology.default_opacity),
        ]


    # Zoom-level adaptation
    if symbology.min_zoom > 0:
        layout["minzoom"] = symbology.min_zoom
    if symbology.max_zoom < 22:
        layout["maxzoom"] = symbology.max_zoom
    return {"paint": paint, "layout": layout}


def auto_generate_style_from_layer(
    layer: Any, palette_name: str = "viridis"
) -> dict[str, Any]:
    """Auto-generate a MapLibre style dict for a layer.

    This is a convenience method that creates a ``SymbologyConfig`` from
    layer defaults and generates a style.  For full auto-generation with
    statistics-based classification, see ``auto.py``.
    """
    # Build a minimal in-memory config surrogate for generation
    config = SymbologyConfig(
        layer=layer,
        symbology_type="single",
        attribute_column="",
        default_color="#888888",
        default_opacity=0.7,
        stroke_color="",
        stroke_width=1.0,
        line_width=1.0,
        circle_radius=4.0,
        palette_name=palette_name,
        reverse_palette=False,
        num_classes=5,
        classification_method="quantile",
        null_handling="gray",
        null_color="",
        zero_transparent=False,
        auto_generated=True,
    )
    return generate_maplibre_style(config)
