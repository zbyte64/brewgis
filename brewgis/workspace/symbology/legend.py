"""Legend data generation from SymbologyConfig models."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brewgis.workspace.models import StyleClass
    from brewgis.workspace.models import SymbologyConfig

GEOMETRY_TYPE_MAP: dict[str, str] = {
    "fill": "fill",
    "line": "line",
    "circle": "circle",
}


@dataclass
class LegendItem:
    """A single legend entry."""

    label: str
    color: str
    opacity: float = 0.7
    type_hint: str = "fill"  # 'fill' | 'line' | 'circle' — matches the layer geometry
    min_value: float | None = None
    max_value: float | None = None
    is_null_item: bool = False


@dataclass
class NullHandlingInfo:
    """Information about null/zero-value handling."""

    null_handling: str  # 'hide' | 'gray' | 'custom_color'
    null_color: str
    zero_transparent: bool
    null_count: int | None = None  # populated later if available


@dataclass
class SymbologyLegend:
    """Complete legend data for a layer's symbology."""

    layer_name: str
    symbology_type: str  # 'single' | 'categorical' | 'graduated'
    attribute_column: str = ""
    items: list[LegendItem] = field(default_factory=list)
    null_info: NullHandlingInfo | None = None


def _resolve_type_hint(geometry_type: str) -> str:
    return GEOMETRY_TYPE_MAP.get(geometry_type, "fill")


def _build_label(cls: StyleClass, index: int) -> str:
    """Return the label for a StyleClass, auto-generating if blank."""
    if cls.label:
        return cls.label
    if cls.min_value is not None and cls.max_value is not None:
        return f"{cls.min_value:.2f} — {cls.max_value:.2f}"
    return f"Class {index + 1}"


def generate_legend(config: SymbologyConfig) -> SymbologyLegend:
    """Generate legend data from a SymbologyConfig."""
    layer = config.layer
    type_hint = _resolve_type_hint(layer.geometry_type)

    legend = SymbologyLegend(
        layer_name=layer.name or layer.key,
        symbology_type=config.symbology_type,
        attribute_column=config.attribute_column,
    )

    if config.symbology_type == "single":
        item = LegendItem(
            label=layer.name or layer.key,
            color=config.default_color,
            opacity=config.default_opacity,
            type_hint=type_hint,
        )
        legend.items.append(item)
    elif config.symbology_type in ("categorical", "graduated"):
        classes = list(config.classes.all())
        for i, cls in enumerate(classes):
            label = _build_label(cls, i)
            item = LegendItem(
                label=label,
                color=cls.color,
                opacity=cls.opacity
                if cls.opacity is not None
                else config.default_opacity,
                type_hint=type_hint,
                min_value=cls.min_value,
                max_value=cls.max_value,
            )
            legend.items.append(item)

    # Null handling
    null_handling = config.null_handling or "gray"
    if null_handling != "hide":
        null_color = config.null_color or "#cccccc"
        null_info = NullHandlingInfo(
            null_handling=null_handling,
            null_color=null_color,
            zero_transparent=config.zero_transparent,
        )
        legend.null_info = null_info

        null_label = "No Data"
        null_item = LegendItem(
            label=null_label,
            color=null_color,
            type_hint=type_hint,
            is_null_item=True,
        )
        legend.items.append(null_item)
    elif config.zero_transparent:
        # zero_transparent is meaningful even when nulls are hidden
        legend.null_info = NullHandlingInfo(
            null_handling=null_handling,
            null_color=config.null_color or "#cccccc",
            zero_transparent=config.zero_transparent,
        )

    return legend
