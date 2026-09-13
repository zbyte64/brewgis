"""Color palette registry for BrewGIS symbology.

Palettes are `cmap <https://github.com/pyapp-kit/cmap>`_ ``Colormap`` objects.
cmap is the source of truth for color data (ColorBrewer, matplotlib, and
other well-known catalogs) *and* for sampling/interpolating within a
palette - this module only decides which catalog entry backs each named
palette, and lets ``Colormap`` do the rest. The one exception is
``material_set1``: Material Design's palette isn't in cmap's catalog, so its
colors are a literal list, wrapped in a ``Colormap`` like everything else so
it behaves identically to every other registry entry.

Palette types
=============
- **Qualitative** - for categorical data.  No perceptual ordering.
- **Sequential** - for numeric data with a low-to-high ordering.  Single hue or
  multi-hue perceptually uniform gradients.
- **Diverging** - for numeric data with a meaningful midpoint (e.g. deviation
  from zero, correlation coefficients).

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

from typing import Final

import numpy as np
from cmap import Colormap

# Material Design 500 palette (first 10) - not in cmap's catalog.
_MATERIAL_SET1_COLORS: Final[list[str]] = [
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
]

# cmap catalog identifiers backing each named palette (everything but
# "material_set1", which is built from the literal list above).
_CATALOG_NAMES: Final[dict[str, str]] = {
    # Qualitative
    "d3_category10": "tab10",
    "brewer_set1": "colorbrewer:Set1_9",
    "pastel1": "colorbrewer:Pastel1_9",
    "dark2": "colorbrewer:Dark2_8",
    "paired": "colorbrewer:Paired_12",
    # Sequential
    "blues": "colorbrewer:Blues_9",
    "greens": "colorbrewer:Greens_9",
    "oranges": "colorbrewer:Oranges_9",
    "reds": "colorbrewer:Reds_9",
    "purples": "colorbrewer:Purples_9",
    "viridis": "matplotlib:viridis",
    "magma": "matplotlib:magma",
    "inferno": "matplotlib:inferno",
    "plasma": "matplotlib:plasma",
    "turbo": "google:turbo",
    # Diverging
    "rdbu": "colorbrewer:RdBu_11",
    "prgn": "colorbrewer:PRGn_11",
    "piyg": "colorbrewer:PiYG_11",
    "rdylbu": "colorbrewer:RdYlBu_11",
    "spectral": "colorbrewer:Spectral_11",
}

QUALITATIVE_NAMES: Final[frozenset[str]] = frozenset(
    {"material_set1", "d3_category10", "brewer_set1", "pastel1", "dark2", "paired"}
)
SEQUENTIAL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "blues",
        "greens",
        "oranges",
        "reds",
        "purples",
        "viridis",
        "magma",
        "inferno",
        "plasma",
        "turbo",
    }
)
DIVERGING_NAMES: Final[frozenset[str]] = frozenset(
    {"rdbu", "prgn", "piyg", "rdylbu", "spectral"}
)


def _build_colormap(name: str) -> Colormap:
    """Build the registry's ``Colormap`` object for palette *name*."""
    if name == "material_set1":
        return Colormap(
            _MATERIAL_SET1_COLORS,
            name=name,
            category="qualitative",
            interpolation="nearest",
        )
    return Colormap(_CATALOG_NAMES[name])


PALETTES: Final[dict[str, Colormap]] = {
    name: _build_colormap(name)
    for name in (*QUALITATIVE_NAMES, *SEQUENTIAL_NAMES, *DIVERGING_NAMES)
}


def get_palette(name: str) -> Colormap:
    """Return the ``Colormap`` registered under *name*.

    Lookup is case-insensitive — every registry key is lowercase, so a
    caller-supplied ``"Blues"``/``"BLUES"`` still resolves to ``"blues"``
    instead of silently failing over to a fallback palette elsewhere.

    Raises ``KeyError`` if *name* is not found. ``Colormap`` is immutable, so
    the object is returned directly rather than copied.
    """
    key = name.lower()
    if key not in PALETTES:
        msg = f"Unknown palette: {name!r}"
        raise KeyError(msg)
    return PALETTES[key]


def get_qualitative_names() -> list[str]:
    """Return sorted list of qualitative palette names."""
    return sorted(QUALITATIVE_NAMES)


def get_sequential_names() -> list[str]:
    """Return sorted list of sequential palette names."""
    return sorted(SEQUENTIAL_NAMES)


def get_diverging_names() -> list[str]:
    """Return sorted list of diverging palette names."""
    return sorted(DIVERGING_NAMES)


def get_all_names() -> list[str]:
    """Return sorted list of all palette names."""
    return sorted(PALETTES)


def interpolate_color(
    colormap: Colormap,
    value: float,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> str:
    """Return the hex color at *value* within *colormap*.

    *value* is clamped to ``[min_val, max_val]`` then normalised to ``[0, 1]``.
    cmap resolves the actual color from there: linearly for sequential/
    diverging palettes, snapped to the nearest class for qualitative ones
    (per the ``Colormap``'s own ``interpolation`` mode) - so a degenerate
    range (``min_val == max_val``) resolves to the midpoint color, ``0.5``.
    """
    if max_val == min_val:
        t = 0.5
    else:
        t = (value - min_val) / (max_val - min_val)
        t = max(0.0, min(1.0, t))
    return colormap(t).hex.lower()


def sample_palette(
    colormap: Colormap,
    n: int,
    *,
    reverse: bool = False,
) -> list[str]:
    """Return *n* colors sampled from *colormap*.

    Qualitative palettes cycle through their native classes (no blending
    between unrelated categories); sequential and diverging palettes are
    sampled evenly across ``colormap``'s own interpolation.
    """
    if n == 0:
        return []

    stops = [stop.color.hex.lower() for stop in colormap.color_stops]
    if n == 1:
        return [stops[-1] if reverse else stops[0]]

    if colormap.category == "qualitative":
        colors = [stops[i % len(stops)] for i in range(n)]
    else:
        colors = [colormap(t).hex.lower() for t in np.linspace(0, 1, n)]

    if reverse:
        colors.reverse()
    return colors


def preview_swatches(max_swatches: int = 11) -> dict[str, list[str]]:
    """Return a JSON-serializable ``{name: [hex, ...]}`` map of every palette.

    Used to hand the palette picker UI something to render swatches from,
    since ``Colormap`` objects (unlike the hex lists this used to return)
    aren't JSON-serializable themselves. Each list is the palette's native
    classes, or ``max_swatches`` evenly-sampled colors for palettes with more
    classes than that (e.g. cmap's continuous, 256-stop matplotlib entries).
    """
    swatches: dict[str, list[str]] = {}
    for name, colormap in PALETTES.items():
        native = len(colormap.color_stops)
        swatches[name] = sample_palette(colormap, min(native, max_swatches))
    return swatches
