"""Auto-generation pipeline for BrewGIS symbology.

Given a Layer and an optional attribute column name, this pipeline:
1. Fetches column statistics from PostGIS
2. Determines if the column is categorical or numeric
3. Selects an appropriate palette and classification method
4. Creates (or updates) SymbologyConfig + StyleClass rows
5. Generates MapLibre style JSON
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.module_registry import get_default_palette
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import StyleClass
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.palettes import get_diverging_names
from brewgis.workspace.palettes import get_palette
from brewgis.workspace.palettes import get_qualitative_names
from brewgis.workspace.palettes import get_sequential_names
from brewgis.workspace.palettes import sample_palette
from brewgis.workspace.symbology.classifiers import classify
from brewgis.workspace.symbology.stats import ColumnStatistics
from brewgis.workspace.symbology.stats import compute_statistics
from brewgis.workspace.symbology.stats import list_columns

if TYPE_CHECKING:
    from cmap import Colormap


def _resolve_zero_transparency(
    existing: SymbologyConfig | None, requested: bool | None
) -> bool:
    """Whether this layer's zero values are drawn as transparent.

    ``requested`` is what the caller asked for; ``None`` keeps the layer's
    current setting, and a layer with no symbology config yet starts with the
    zeros visible.
    """
    if requested is not None:
        return requested
    return bool(existing and existing.zero_transparent)


def _suggest_palette(
    stats: ColumnStatistics,
) -> str:
    """Suggest a palette name based on the column statistics."""
    if stats.is_categorical:
        return "material_set1"
    if (
        stats.mean is not None
        and stats.min_value is not None
        and stats.max_value is not None
    ):
        # Diverging palettes work well when the mean is near the middle of the range
        mid = (stats.min_value + stats.max_value) / 2.0
        range_pct = abs(stats.mean - mid) / (stats.max_value - stats.min_value + 1e-12)
        if range_pct < 0.2:
            return "rdbu"
    return "viridis"


def _suggest_symbology_type(stats: ColumnStatistics) -> str:
    """Suggest a symbology type based on heuristics."""
    if stats.is_categorical:
        return "categorical"
    if stats.distinct_count <= 2:
        return "categorical"
    return "graduated"


def _suggest_classification_method(stats: ColumnStatistics) -> str:
    """Suggest a classification method based on data shape."""
    if stats.is_categorical:
        return "quantile"

    # Check for skew using mean/median ratio
    if stats.mean is not None and stats.median is not None and stats.median != 0:
        skew_ratio = stats.mean / stats.median
        if skew_ratio > 2.0 or skew_ratio < 0.5:
            return "logarithmic"

    # Check for clustering using stddev/range ratio
    if (
        stats.stddev is not None
        and stats.min_value is not None
        and stats.max_value is not None
        and stats.max_value > stats.min_value
    ):
        range_val = stats.max_value - stats.min_value
        cv = stats.stddev / range_val
        if cv < 0.1:
            return "natural_breaks"

    return "quantile"


def resolve_symbology_source(layer: Layer, scenario: Scenario) -> tuple[str, str]:
    """Return the ``(schema, table)`` symbology should read *layer* from.

    For the workspace's base canvas layer, this is *scenario*'s effective
    base layer (see ``Scenario.base_layer_source``) — the raw base table for
    a BASE scenario, or the scenario's canvas view (base canvas COALESCEd
    with any PaintedCanvas overrides) for an ALTERNATIVE one — so
    breaks/categories reflect painted values instead of silently ignoring
    them. Any other layer (not paintable) always uses its own raw table
    regardless of scenario.
    """
    if layer.key == BASE_CANVAS_LAYER_KEY:
        return scenario.base_layer_source()
    schema = layer.db_schema or layer.workspace.db_schema
    return schema, layer.db_table


_PALETTE_QUALITATIVE_NAMES = frozenset(get_qualitative_names())
_PALETTE_SEQUENTIAL_NAMES = frozenset(get_sequential_names())
_PALETTE_DIVERGING_NAMES = frozenset(get_diverging_names())
_CATEGORICAL_PALETTES = _PALETTE_QUALITATIVE_NAMES
_NUMERIC_PALETTES = _PALETTE_SEQUENTIAL_NAMES | _PALETTE_DIVERGING_NAMES


def auto_generate_symbology(  # noqa: PLR0913
    layer: Layer,
    attribute_column: str | None = None,
    *,
    palette_name: str | None = None,
    num_classes: int = 5,
    classification_method: str | None = None,
    reverse_palette: bool = False,
    commit: bool = True,
    scenario: Scenario | None = None,
    zero_transparent: bool | None = None,
) -> SymbologyConfig:
    """Auto-generate a symbology configuration for *layer*.

    1. Computes column statistics for *attribute_column* (or the first
       suitable numeric/categorical column if ``None``).
    2. Selects palette, symbology type, and classification method via
       heuristics.
    3. Creates/updates ``SymbologyConfig`` and ``StyleClass`` rows.
    4. Returns the (saved, unless ``commit=False``) ``SymbologyConfig``.

    Parameters
    ----------
    layer:
        The Layer to generate symbology for.
    attribute_column:
        Column name to style on.  If ``None``, the first suitable column
        from the table is auto-selected.
    palette_name:
        Palette to use.  ``None`` = the result table's registered default if it
        has one (see ``module_registry.TABLE_PALETTE``), else one suggested
        from the column's statistics.
    num_classes:
        Number of classes (default 5).
    classification_method:
        Classification method.  ``None`` = auto-select.
    reverse_palette:
        When ``True``, sample the palette in reverse order.
    commit:
        When ``True`` (default), persists the config and replaces its
        ``StyleClass`` rows in the database. When ``False``, computes the
        same result but does not write to the database — useful for a live
        preview (e.g. while the user is still picking a column) that should
        only be committed when they explicitly save. The computed style
        classes are attached to the returned config as
        ``preview_style_classes`` rather than being queryable via
        ``config.classes.all()``.
    scenario:
        When given and *layer* is the workspace's base canvas layer, breaks
        and statistics are computed from this scenario's canvas view
        (base canvas COALESCEd with any PaintedCanvas overrides) instead of
        the raw base table — so painted values are reflected. Ignored for
        any other layer.
    zero_transparent:
        Whether zero values are drawn as transparent. ``None`` (the default)
        keeps the layer's current setting, and a new layer starts with it
        off. When it is on, the zeros are also left out of the statistics and
        the classification (see ``stats.compute_statistics``): a value the map
        hides must not consume one of the requested classes.

    Returns
    -------
    SymbologyConfig
        The configuration (saved unless ``commit=False``).
    """
    # resolve_symbology_source now requires a real Scenario (it defers to
    # Scenario.base_layer_source(), which needs a scenario_type to decide
    # between the raw base table and a canvas view) — callers here may pass
    # None (e.g. scenario_cloner.py's post-create symbology generation, with
    # no scenario context in play), so fall back to the workspace's BASE
    # scenario, which resolves to the same raw base table None used to.
    resolved_scenario = scenario or layer.workspace.scenarios.get(
        scenario_type=ScenarioType.BASE
    )
    schema, table = resolve_symbology_source(layer, resolved_scenario)

    if attribute_column:
        col = attribute_column
    else:
        # Auto-pick the first suitable column

        cols = list_columns(schema, table)
        numeric_cols = [
            c
            for c in cols
            if c["type"]
            in {
                "int4",
                "int8",
                "float4",
                "float8",
                "numeric",
            }
        ]
        if numeric_cols:
            col = numeric_cols[0]["name"]
        elif cols:
            col = cols[0]["name"]
        else:
            col = ""

    if not col:
        return _create_default_config(layer, commit=commit)

    # Auto re-derives the classes; it does not get to decide how absent
    # values are drawn, so an unspecified flag means "leave the layer's
    # setting alone" rather than "reset it".
    existing = SymbologyConfig.objects.filter(layer=layer).first()
    excludes_zero = _resolve_zero_transparency(existing, zero_transparent)

    stats = compute_statistics(schema, table, col, exclude_zero=excludes_zero)

    used_palette = _resolve_palette_name(palette_name, table, stats)
    used_method = classification_method or _suggest_classification_method(stats)
    used_type = _suggest_symbology_type(stats)

    # Build style classes
    class_rows: list[dict[str, Any]] = []

    if used_type == "categorical":
        # One class per distinct value, and the palette is sampled for exactly
        # that many classes: the index is what pairs a class with its color, so
        # sampling a fixed 20 left every value past the 20th reusing a color
        # from earlier in the palette — 44 built form keys over a 10-color
        # palette came out 4 colors deep. A palette with fewer stops than there
        # are classes still repeats them, per ``sample_palette``.
        palette = _resolve_palette(
            _get_palette_list(used_palette, stats),
            stats.distinct_count,
            reverse=reverse_palette,
        )
        if stats.frequencies:
            for i, val in enumerate(stats.frequencies):
                class_rows.append(
                    {
                        "label": str(val),
                        "color": palette[i % len(palette)],
                        "sort_order": i,
                        "min_value": None,
                        "max_value": None,
                    }
                )
    else:
        # Graduated: run classification
        result = classify(
            stats,
            method=used_method,
            num_classes=num_classes,
            schema=schema,
            table=table,
            column=col,
            exclude_zero=excludes_zero,
        )
        palette = _resolve_palette(
            _get_palette_list(used_palette, stats),
            len(result.breaks) - 1,
            reverse=reverse_palette,
        )
        for i in range(len(result.breaks) - 1):
            class_rows.append(
                {
                    "label": result.labels[i] if i < len(result.labels) else "",
                    "color": palette[i % len(palette)],
                    "sort_order": i,
                    "min_value": result.breaks[i],
                    "max_value": result.breaks[i + 1],
                }
            )

    if commit:
        # Create or update SymbologyConfig
        config, _created = SymbologyConfig.objects.update_or_create(
            layer=layer,
            defaults={
                "symbology_type": used_type,
                "attribute_column": col,
                "default_color": "#888888",
                "default_opacity": 0.7,
                "palette_name": used_palette,
                "reverse_palette": reverse_palette,
                "num_classes": num_classes,
                "classification_method": used_method,
                "null_handling": existing.null_handling if existing else "gray",
                "null_color": existing.null_color if existing else "",
                "zero_transparent": excludes_zero,
                "auto_generated": True,
            },
        )
        # Replace StyleClass rows
        config.classes.all().delete()
        for row_data in class_rows:
            StyleClass.objects.create(symbology=config, **row_data)
        return config

    # Preview only — reuse the existing config's non-classification fields
    # (color/opacity/stroke/etc.) so previewing a new column, palette, or
    # class count doesn't clobber settings the user already customized.
    try:
        config = SymbologyConfig.objects.get(layer=layer)
    except SymbologyConfig.DoesNotExist:
        config = SymbologyConfig(layer=layer)
    config.symbology_type = used_type
    config.attribute_column = col
    config.palette_name = used_palette
    config.reverse_palette = reverse_palette
    config.num_classes = num_classes
    config.classification_method = used_method
    config.zero_transparent = excludes_zero
    config.preview_style_classes = [
        StyleClass(symbology=config, **row_data) for row_data in class_rows
    ]
    return config


def _resolve_palette(
    colormap: Colormap, count: int, *, reverse: bool = False
) -> list[str]:
    """Sample *count* colors from *colormap*, optionally reversed."""
    palette = sample_palette(colormap, count)
    return list(reversed(palette)) if reverse else palette


def _resolve_palette_name(
    requested: str | None, table: str, stats: ColumnStatistics
) -> str:
    """Pick the palette to classify with, in order of authority.

    1. What the caller asked for — an explicit palette is never overridden.
    2. The result table's registered default (``module_registry.TABLE_PALETTE``)
       — an analysis layer keeps the palette chosen for its metric, whether it
       is being registered by a run or re-generated from the editor.
    3. A palette suggested by the column's own statistics.
    """
    return (requested or get_default_palette(table) or _suggest_palette(stats)).lower()


def _get_palette_list(name: str, stats: ColumnStatistics) -> Colormap:
    """Return palette Colormap by name, falling back on sensible defaults."""
    try:
        return get_palette(name)
    except KeyError:
        if stats.is_categorical:
            return get_palette("material_set1")
        return get_palette("viridis")


def _create_default_config(layer: Layer, *, commit: bool = True) -> SymbologyConfig:
    """Create a minimal single-symbol config when no suitable column is found."""
    if commit:
        config, _created = SymbologyConfig.objects.update_or_create(
            layer=layer,
            defaults={
                "symbology_type": "single",
                "attribute_column": "",
                "default_color": "#888888",
                "default_opacity": 0.7,
                "auto_generated": True,
            },
        )
        return config

    try:
        config = SymbologyConfig.objects.get(layer=layer)
    except SymbologyConfig.DoesNotExist:
        config = SymbologyConfig(
            layer=layer, default_color="#888888", default_opacity=0.7
        )
    config.symbology_type = "single"
    config.attribute_column = ""
    config.preview_style_classes = []
    return config
