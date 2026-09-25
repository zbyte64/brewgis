"""Color palette registry for BrewGIS symbology.

Palettes are `cmap <https://github.com/pyapp-kit/cmap>`_ ``Colormap`` objects.
cmap is the source of truth for color data (ColorBrewer, matplotlib, and
other well-known catalogs) *and* for sampling/interpolating within a
palette - this module only decides which catalog entry backs each named
palette, and lets ``Colormap`` do the rest. Two entries are built here
instead of taken from the catalog as-is: ``material_set1``, whose Material
Design colors aren't in cmap at all, and ``glasbey``, whose colors are -
but under a continuous ``miscellaneous`` entry, and with the near-white and
near-black ends of the sequence dropped (see ``_glasbey_colors``). Both are
wrapped in a ``Colormap`` like everything else so they behave identically to
every other registry entry.

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

# Glasbey's categorical colors: cmap ships them as a 256-stop continuous
# "miscellaneous" entry, but the sequence is not a gradient - it is ordered so
# that every prefix is as distinct as the method (Glasbey et al., "Colour
# displays for categorical images") could make it, which is what a layer with
# 40+ categories needs. The ends of the sequence are dropped, because a map
# cannot show them: the near-white stops are invisible over a light basemap,
# and the near-black ones read as holes - and disappear against dark UI chrome.
_GLASBEY_MIN_LUMINANCE: Final[float] = 0.02
_GLASBEY_MAX_LUMINANCE: Final[float] = 0.75

# sRGB's linear-segment cutoff (WCAG's relative-luminance definition).
_SRGB_LINEAR_THRESHOLD: Final[float] = 0.03928


def _relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance of a ``#rrggbb`` color."""
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        c / 12.92 if c <= _SRGB_LINEAR_THRESHOLD else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _glasbey_colors() -> list[str]:
    """Return cmap's glasbey colors, minus those a map cannot show."""
    return [
        stop.color.hex.lower()
        for stop in Colormap("glasbey").color_stops
        if _GLASBEY_MIN_LUMINANCE
        <= _relative_luminance(stop.color.hex)
        <= _GLASBEY_MAX_LUMINANCE
    ]


_GLASBEY_COLORS: Final[list[str]] = _glasbey_colors()

# cmap catalog identifiers backing each named palette (everything but
# "material_set1", built from the literal list above, and "glasbey", built
# from the filtered ``_GLASBEY_COLORS``).
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
    {
        "material_set1",
        "glasbey",
        "d3_category10",
        "brewer_set1",
        "pastel1",
        "dark2",
        "paired",
    }
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
    if name == "glasbey":
        # cmap files it under "miscellaneous" with linear interpolation, which
        # would have the generator blend neighbouring categories; re-wrap it so
        # it samples stop-to-stop like every other categorical palette.
        return Colormap(
            _GLASBEY_COLORS,
            name=name,
            category="qualitative",
            interpolation="nearest",
        )
    return Colormap(_CATALOG_NAMES[name])


PALETTES: Final[dict[str, Colormap]] = {
    name: _build_colormap(name)
    for name in (*QUALITATIVE_NAMES, *SEQUENTIAL_NAMES, *DIVERGING_NAMES)
}

MAX_CATEGORICAL_COLORS: Final[int] = max(
    len(PALETTES[name].color_stops) for name in QUALITATIVE_NAMES
)
"""Number of colors in the largest qualitative palette.

A categorical layer cannot distinguish more values than this — past it the
palette repeats colors (see :func:`sample_palette`) — so callers that build
one class per distinct value (``symbology.stats.compute_statistics``) stop
fetching there.
"""


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
    classes when it has at most *max_swatches* of them; a palette with more
    (glasbey's ~200, cmap's 256-stop continuous entries) is shown as its
    first *max_swatches* — the leading, most-distinct classes for a
    qualitative palette, evenly-spaced samples for a continuous one.
    """
    swatches: dict[str, list[str]] = {}
    for name, colormap in PALETTES.items():
        native = len(colormap.color_stops)
        swatches[name] = sample_palette(colormap, min(native, max_swatches))
    return swatches
