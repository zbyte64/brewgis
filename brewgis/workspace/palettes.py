"""Color palette registry for BrewGIS symbology.

Palettes are defined as immutable Python data - code is the source of truth, not the
database.  Each palette is a list of hex color strings.

Palette types
=============
- **Qualitative** - for categorical data.  No perceptual ordering.
- **Sequential** - for numeric data with a low-to-high ordering.  Single hue or
  multi-hue perceptually uniform gradients.
- **Diverging** - for numeric data with a meaningful midpoint (e.g. deviation from
  zero, correlation coefficients).

Selection hints
===============
- Categorical fields -> qualitative palette.
- Numeric fields with a natural low-high -> sequential palette.
- Numeric fields with a meaningful zero / midpoint -> diverging palette.

The module-level dictionary ``PALETTES`` is the canonical registry.  Consumers
should access palettes via ``get_palette(name)`` rather than reaching into the
dict directly, so that aliases and deprecation can be handled in one place.
"""

from __future__ import annotations

import math
from typing import Final

# =========================================================================
# Qualitative
# =========================================================================

QUALITATIVE: Final[dict[str, list[str]]] = {
    # Material Design 500 palette (first 10)
    "material_set1": [
        "#4CAF50",  # Green
        "#2196F3",  # Blue
        "#9E9E9E",  # Grey
        "#9C27B0",  # Purple
        "#FF9800",  # Orange
        "#F44336",  # Red
        "#00BCD4",  # Cyan
        "#FFEB3B",  # Yellow
        "#795548",  # Brown
        "#607D8B",  # Blue Grey
    ],
    # D3 scale-chromatic category 10
    "d3_category10": [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ],
    # ColorBrewer qualitative Set1 (9 classes max)
    "brewer_set1": [
        "#e41a1c",
        "#377eb8",
        "#4daf4a",
        "#984ea3",
        "#ff7f00",
        "#ffff33",
        "#a65628",
        "#f781bf",
        "#999999",
    ],
    "pastel1": [
        "#fbb4ae",
        "#b3cde3",
        "#ccebc5",
        "#decbe4",
        "#fed9a6",
        "#ffffcc",
        "#e5d8bd",
        "#fddaec",
        "#f2f2f2",
    ],
    "dark2": [
        "#1b9e77",
        "#d95f02",
        "#7570b3",
        "#e7298a",
        "#66a61e",
        "#e6ab02",
        "#a6761d",
        "#666666",
    ],
    "paired": [
        "#a6cee3",
        "#1f78b4",
        "#b2df8a",
        "#33a02c",
        "#fb9a99",
        "#e31a1c",
        "#fdbf6f",
        "#ff7f00",
        "#cab2d6",
        "#6a3d9a",
    ],
}

# =========================================================================
# Sequential
# =========================================================================

SEQUENTIAL: Final[dict[str, list[str]]] = {
    "blues": [
        "#f7fbff",
        "#deebf7",
        "#c6dbef",
        "#9ecae1",
        "#6baed6",
        "#4292c6",
        "#2171b5",
        "#08519c",
        "#08306b",
    ],
    "greens": [
        "#f7fcf5",
        "#e5f5e0",
        "#c7e9c0",
        "#a1d99b",
        "#74c476",
        "#41ab5d",
        "#238b45",
        "#006d2c",
        "#00441b",
    ],
    "oranges": [
        "#fff5eb",
        "#fee6ce",
        "#fdd0a2",
        "#fdae6b",
        "#fd8d3c",
        "#f16913",
        "#d94801",
        "#a63603",
        "#7f2704",
    ],
    "reds": [
        "#fff5f0",
        "#fee0d2",
        "#fcbba1",
        "#fc9272",
        "#fb6a4a",
        "#ef3b2c",
        "#cb181d",
        "#a50f15",
        "#67000d",
    ],
    "purples": [
        "#fcfbfd",
        "#efedf5",
        "#dadaeb",
        "#bcbddc",
        "#9e9ac8",
        "#807dba",
        "#6a51a3",
        "#54278f",
        "#3f007d",
    ],
    # matplotlib default - perceptually uniform
    "viridis": [
        "#440154",
        "#3b528b",
        "#21918c",
        "#5ec962",
        "#fde725",
    ],
    "magma": [
        "#000004",
        "#3b0f6f",
        "#8c2981",
        "#de4968",
        "#fe9f6d",
        "#fcfdbf",
    ],
    "inferno": [
        "#000004",
        "#42049b",
        "#c53c6e",
        "#f28e2b",
        "#fcfcbf",
    ],
    "plasma": [
        "#0d0887",
        "#6a00a8",
        "#b12a90",
        "#e16462",
        "#fca636",
        "#f0f921",
    ],
    "turbo": [
        "#30123b",
        "#4662c3",
        "#36a6e3",
        "#14d3e2",
        "#09f5c0",
        "#3af56b",
        "#a2e34a",
        "#f8c73e",
        "#f68c2a",
        "#e34e23",
        "#c51d28",
    ],
}

# =========================================================================
# Diverging
# =========================================================================

DIVERGING: Final[dict[str, list[str]]] = {
    "rdbu": [
        "#b2182b",
        "#ef8a62",
        "#fddbc7",
        "#f7f7f7",
        "#d1e5f0",
        "#67a9cf",
        "#2166ac",
    ],
    "prgn": [
        "#762a83",
        "#af8dc3",
        "#e7d4e8",
        "#f7f7f7",
        "#d9f0d3",
        "#7fbf7b",
        "#1b7837",
    ],
    "piyg": [
        "#c51b7d",
        "#e9a3c9",
        "#fde0ef",
        "#f7f7f7",
        "#e6f5d0",
        "#a1d76a",
        "#4d9221",
    ],
    "rdylbu": [
        "#d73027",
        "#f46d43",
        "#fdae61",
        "#fee090",
        "#ffffbf",
        "#e0f3f8",
        "#abd9e9",
        "#74add1",
        "#4575b4",
    ],
    "spectral": [
        "#d53e4f",
        "#f46d43",
        "#fdae61",
        "#fee08b",
        "#ffffbf",
        "#e6f598",
        "#abdda4",
        "#66c2a5",
        "#3288bd",
    ],
}

# =========================================================================
# Registry
# =========================================================================

PALETTES: Final[dict[str, list[str]]] = {}
PALETTES.update(QUALITATIVE)
PALETTES.update(SEQUENTIAL)
PALETTES.update(DIVERGING)


def get_palette(name: str) -> list[str]:
    """Return the palette list by name.

    Raises ``KeyError`` if *name* is not found.
    """
    if name not in PALETTES:
        msg = f"Unknown palette: {name!r}"
        raise KeyError(msg)
    return list(PALETTES[name])


def get_qualitative_names() -> list[str]:
    """Return sorted list of qualitative palette names."""
    return sorted(QUALITATIVE)


def get_sequential_names() -> list[str]:
    """Return sorted list of sequential palette names."""
    return sorted(SEQUENTIAL)


def get_diverging_names() -> list[str]:
    """Return sorted list of diverging palette names."""
    return sorted(DIVERGING)


def get_all_names() -> list[str]:
    """Return sorted list of all palette names."""
    return sorted(PALETTES)


def _parse_hex(hex_color: str) -> tuple[int, int, int]:
    """Parse a hex color string *(#rgb, #rrggbb)* to ``(r, g, b)`` ints."""
    h = hex_color.lstrip("#")
    short_hex = 3
    if len(h) == short_hex:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _hex_from_rgb(r: int, g: int, b: int) -> str:
    """Format ``(r, g, b)`` ints as ``#rrggbb``."""
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_color(
    palette: list[str],
    value: float,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> str:
    """Linearly interpolate a colour from *palette* at a normalised *value*.

    *value* is clamped to ``[min_val, max_val]``, then re-mapped to the
    palette index range.  The result is a hex string.

    If *palette* has only one colour it is returned directly (no
    interpolation).  Otherwise the palette is treated as a gradient and
    interpolation is performed in RGB space.

    Works correctly for any *value* >= 0 (integers or floats), palette of
    length >= 1, and when *min_val* == *max_val*.
    """
    if not palette:
        msg = "Cannot interpolate over an empty palette."
        raise ValueError(msg)
    if len(palette) == 1:
        return palette[0]

    # Clamp and normalise
    if max_val == min_val:
        # Degenerate range - return the mid-point colour
        mid = len(palette) // 2
        return palette[mid]

    t_val = (value - min_val) / (max_val - min_val)
    t_val = max(0.0, min(1.0, t_val))

    # Map t_val -> palette index with fractional part
    idx = t_val * (len(palette) - 1)
    low = math.floor(idx)
    high = min(low + 1, len(palette) - 1)
    frac = idx - low

    frac_eps = 0.01
    if frac < frac_eps:
        return palette[low]
    if frac > 1.0 - frac_eps:
        return palette[high]

    r1, g1, b1 = _parse_hex(palette[low])
    r2, g2, b2 = _parse_hex(palette[high])

    return _hex_from_rgb(
        round(r1 + (r2 - r1) * frac),
        round(g1 + (g2 - g1) * frac),
        round(b1 + (b2 - b1) * frac),
    )


def sample_palette(
    palette: list[str],
    n: int,
    *,
    reverse: bool = False,
) -> list[str]:
    """Return *n* evenly-spaced colours from *palette*.

    When ``n <= len(palette)`` the colours are drawn at even intervals.
    When ``n > len(palette)`` the palette is interpolated linearly in RGB
    space between its stops.
    """
    if n == 0:
        return []
    if n == 1:
        return [palette[-1] if reverse else palette[0]]

    colours = [interpolate_color(palette, i, 0, n - 1) for i in range(n)]
    if reverse:
        colours.reverse()
    return colours
