"""Auto-generation pipeline for BrewGIS symbology.

Given a Layer and an optional attribute column name, this pipeline:
1. Fetches column statistics from PostGIS
2. Determines if the column is categorical or numeric
3. Selects an appropriate palette and classification method
4. Creates (or updates) SymbologyConfig + StyleClass rows
5. Generates MapLibre style JSON
"""

from __future__ import annotations

from typing import Any

from brewgis.workspace.models import Layer
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


_PALETTE_QUALITATIVE_NAMES = frozenset(get_qualitative_names())
_PALETTE_SEQUENTIAL_NAMES = frozenset(get_sequential_names())
_PALETTE_DIVERGING_NAMES = frozenset(get_diverging_names())
_CATEGORICAL_PALETTES = _PALETTE_QUALITATIVE_NAMES
_NUMERIC_PALETTES = _PALETTE_SEQUENTIAL_NAMES | _PALETTE_DIVERGING_NAMES


def auto_generate_symbology(
    layer: Layer,
    attribute_column: str | None = None,
    *,
    palette_name: str | None = None,
    num_classes: int = 5,
    classification_method: str | None = None,
) -> SymbologyConfig:
    """Auto-generate a symbology configuration for *layer*.

    1. Computes column statistics for *attribute_column* (or the first
       suitable numeric/categorical column if ``None``).
    2. Selects palette, symbology type, and classification method via
       heuristics.
    3. Creates/updates ``SymbologyConfig`` and ``StyleClass`` rows.
    4. Returns the saved ``SymbologyConfig``.

    Parameters
    ----------
    layer:
        The Layer to generate symbology for.
    attribute_column:
        Column name to style on.  If ``None``, the first suitable column
        from the table is auto-selected.
    palette_name:
        Palette to use.  ``None`` = auto-select.
    num_classes:
        Number of classes (default 5).
    classification_method:
        Classification method.  ``None`` = auto-select.

    Returns
    -------
    SymbologyConfig
        The saved configuration (with related ``StyleClass`` rows).
    """
    schema = layer.workspace.db_schema
    table = layer.db_table

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
        return _create_default_config(layer)

    stats = compute_statistics(schema, table, col)

    used_palette = palette_name or _suggest_palette(stats)
    used_method = classification_method or _suggest_classification_method(stats)
    used_type = _suggest_symbology_type(stats)

    # Build style classes
    class_rows: list[dict[str, Any]] = []

    if used_type == "categorical":
        # One class per distinct value
        palette = sample_palette(
            _get_palette_list(used_palette, stats),
            min(stats.distinct_count, 20),
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
        )
        palette = sample_palette(
            _get_palette_list(used_palette, stats),
            len(result.breaks) - 1,
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

    # Create or update SymbologyConfig
    config, created = SymbologyConfig.objects.update_or_create(
        layer=layer,
        defaults={
            "symbology_type": used_type,
            "attribute_column": col,
            "default_color": "#888888",
            "default_opacity": 0.7,
            "palette_name": used_palette,
            "reverse_palette": False,
            "num_classes": num_classes,
            "classification_method": used_method,
            "null_handling": "gray",
            "null_color": "",
            "zero_transparent": False,
            "auto_generated": True,
        },
    )

    # Replace StyleClass rows
    config.classes.all().delete()
    for row_data in class_rows:
        StyleClass.objects.create(symbology=config, **row_data)

    return config


def _get_palette_list(name: str, stats: ColumnStatistics) -> list[str]:
    """Return palette list by name, falling back on sensible defaults."""
    try:
        return get_palette(name)
    except KeyError:
        if stats.is_categorical:
            return get_palette("material_set1")
        return get_palette("viridis")


def _create_default_config(layer: Layer) -> SymbologyConfig:
    """Create a minimal single-symbol config when no suitable column is found."""
    config, _ = SymbologyConfig.objects.update_or_create(
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
