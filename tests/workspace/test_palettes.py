"""Tests for the BrewGIS palette registry."""

from __future__ import annotations

import json

import pytest
from cmap import Colormap

from brewgis.workspace.palettes import PALETTES
from brewgis.workspace.palettes import get_all_names
from brewgis.workspace.palettes import get_diverging_names
from brewgis.workspace.palettes import get_palette
from brewgis.workspace.palettes import get_qualitative_names
from brewgis.workspace.palettes import get_sequential_names
from brewgis.workspace.palettes import interpolate_color
from brewgis.workspace.palettes import preview_swatches
from brewgis.workspace.palettes import sample_palette


class TestPaletteRegistry:
    def test_all_palettes_accessible_by_name(self) -> None:
        """Every palette in PALETTES dict is retrievable via get_palette()."""
        for name in PALETTES:
            assert get_palette(name) is PALETTES[name]

    def test_get_palette_returns_colormap(self) -> None:
        assert isinstance(get_palette("blues"), Colormap)

    def test_get_palette_unknown_key(self) -> None:
        with pytest.raises(KeyError, match="does_not_exist"):
            get_palette("does_not_exist")

    def test_get_qualitative_names(self) -> None:
        names = get_qualitative_names()
        assert "material_set1" in names
        assert "d3_category10" in names
        assert "blues" not in names  # blues is sequential

    def test_get_sequential_names(self) -> None:
        names = get_sequential_names()
        assert "blues" in names
        assert "viridis" in names
        assert "material_set1" not in names

    def test_get_diverging_names(self) -> None:
        names = get_diverging_names()
        assert "rdbu" in names
        assert "spectral" in names
        assert "blues" not in names

    def test_get_all_names(self) -> None:
        all_names = get_all_names()
        assert len(all_names) > 20
        assert all_names == sorted(PALETTES)

    def test_palettes_have_valid_hex_colors(self) -> None:
        """Every color stop in every palette is a valid 6-digit hex string."""
        for name, colormap in PALETTES.items():
            for stop in colormap.color_stops:
                color = stop.color.hex
                assert color.startswith("#"), f"{name}: {color}"
                assert len(color) == 7, f"{name}: {color}"
                int(color[1:], 16)  # should not raise

    def test_qualitative_palettes_use_nearest_interpolation(self) -> None:
        """Categorical palettes must not blend between unrelated classes."""
        for name in get_qualitative_names():
            assert get_palette(name).category == "qualitative"
            assert get_palette(name).interpolation == "nearest"

    def test_material_set1_is_a_colormap(self) -> None:
        """material_set1 isn't in cmap's catalog but is still first-class."""
        colormap = get_palette("material_set1")
        assert isinstance(colormap, Colormap)
        assert colormap.color_stops[0].color.hex.lower() == "#4caf50"


class TestInterpolateColor:
    def test_single_stop_index(self) -> None:
        colormap = get_palette("viridis")
        first = colormap.color_stops[0].color.hex.lower()
        last = colormap.color_stops[-1].color.hex.lower()
        assert interpolate_color(colormap, 0, 0, 1) == first
        assert interpolate_color(colormap, 1, 0, 1) == last

    def test_degenerate_range_returns_midpoint(self) -> None:
        """When min_val == max_val, return the colormap's midpoint color."""
        colormap = get_palette("rdylbu")  # 11 stops, odd -> exact middle
        mid_stop = colormap.color_stops[len(colormap.color_stops) // 2]
        result = interpolate_color(colormap, 42.0, 42.0, 42.0)
        assert result == mid_stop.color.hex.lower()

    def test_clamp_low(self) -> None:
        colormap = get_palette("blues")
        expected = sample_palette(colormap, 1)[0]
        assert interpolate_color(colormap, -100, 0, 100) == expected

    def test_clamp_high(self) -> None:
        colormap = get_palette("blues")
        expected = colormap.color_stops[-1].color.hex.lower()
        assert interpolate_color(colormap, 200, 0, 100) == expected

    def test_qualitative_snaps_to_nearest_class(self) -> None:
        colormap = get_palette("material_set1")
        result = interpolate_color(colormap, 0.05, 0, 1)
        assert result == colormap.color_stops[0].color.hex.lower()


class TestSamplePalette:
    def test_n_zero(self) -> None:
        assert sample_palette(get_palette("viridis"), 0) == []

    def test_n_one(self) -> None:
        colormap = get_palette("viridis")
        result = sample_palette(colormap, 1)
        assert result == [colormap.color_stops[0].color.hex.lower()]

    def test_n_one_reverse(self) -> None:
        colormap = get_palette("viridis")
        result = sample_palette(colormap, 1, reverse=True)
        assert result == [colormap.color_stops[-1].color.hex.lower()]

    def test_n_equals_native_stops(self) -> None:
        colormap = get_palette("blues")
        native = len(colormap.color_stops)
        result = sample_palette(colormap, native)
        assert len(result) == native
        assert result[0] == colormap.color_stops[0].color.hex.lower()
        assert result[-1] == colormap.color_stops[-1].color.hex.lower()

    def test_n_greater_than_native_stops(self) -> None:
        colormap = get_palette("rdbu")  # 11 native stops
        result = sample_palette(colormap, 20)
        assert len(result) == 20

    def test_reverse(self) -> None:
        colormap = get_palette("blues")
        forward = sample_palette(colormap, 5)
        backward = sample_palette(colormap, 5, reverse=True)
        assert backward == list(reversed(forward))

    def test_qualitative_cycles_native_classes_without_blending(self) -> None:
        """Requesting more classes than a qualitative palette has cycles,
        rather than blending unrelated categories together."""
        colormap = get_palette("material_set1")
        native = [stop.color.hex.lower() for stop in colormap.color_stops]
        result = sample_palette(colormap, len(native) + 2)
        assert result == [*native, native[0], native[1]]


class TestPreviewSwatches:
    def test_returns_every_palette(self) -> None:
        swatches = preview_swatches()
        assert set(swatches) == set(get_all_names())

    def test_json_serializable(self) -> None:
        json.dumps(preview_swatches())  # should not raise

    def test_caps_continuous_palettes(self) -> None:
        swatches = preview_swatches(max_swatches=11)
        assert len(swatches["viridis"]) == 11

    def test_keeps_small_native_palettes_uncapped(self) -> None:
        swatches = preview_swatches(max_swatches=11)
        assert len(swatches["dark2"]) == len(get_palette("dark2").color_stops)
