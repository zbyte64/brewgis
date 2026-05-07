"""Tests for the BrewGIS palette registry."""

from __future__ import annotations

import pytest

from brewgis.workspace.palettes import PALETTES
from brewgis.workspace.palettes import _hex_from_rgb
from brewgis.workspace.palettes import _parse_hex
from brewgis.workspace.palettes import get_all_names
from brewgis.workspace.palettes import get_diverging_names
from brewgis.workspace.palettes import get_palette
from brewgis.workspace.palettes import get_qualitative_names
from brewgis.workspace.palettes import get_sequential_names
from brewgis.workspace.palettes import interpolate_color
from brewgis.workspace.palettes import sample_palette


class TestPaletteRegistry:
    def test_all_palettes_accessible_by_name(self) -> None:
        """Every palette in PALETTES dict is retrievable via get_palette()."""
        for name in PALETTES:
            retrieved = get_palette(name)
            assert retrieved == PALETTES[name]

    def test_get_palette_returns_copy(self) -> None:
        """get_palette should return a mutable copy, not the original."""
        original = PALETTES["blues"]
        retrieved = get_palette("blues")
        retrieved.append("#000000")
        assert retrieved != original

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
        """Every color in every palette is a valid 6-digit hex string."""
        for name, palette in PALETTES.items():
            for color in palette:
                assert color.startswith("#"), f"{name}: {color}"
                assert len(color) == 7, f"{name}: {color}"
                int(color[1:], 16)  # should not raise


class TestParseHex:
    def test_full_hex(self) -> None:
        assert _parse_hex("#ff0000") == (255, 0, 0)

    def test_short_hex(self) -> None:
        assert _parse_hex("#f00") == (255, 0, 0)

    def test_mixed(self) -> None:
        assert _parse_hex("#1a2b3c") == (26, 43, 60)


class TestHexFromRgb:
    def test_basic(self) -> None:
        assert _hex_from_rgb(255, 0, 0) == "#ff0000"

    def test_zero_padding(self) -> None:
        assert _hex_from_rgb(10, 20, 30) == "#0a141e"


class TestInterpolateColor:
    def test_single_color_palette(self) -> None:
        assert interpolate_color(["#ff0000"], 0.5) == "#ff0000"

    def test_empty_palette(self) -> None:
        with pytest.raises(ValueError, match="empty palette"):
            interpolate_color([], 0.5)

    def test_degenerate_range(self) -> None:
        """When min_val == max_val, return midpoint color."""
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        result = interpolate_color(palette, 42.0, 42.0, 42.0)
        assert result == "#00ff00"  # middle of 3

    def test_clamp_low(self) -> None:
        palette = ["#000000", "#ffffff"]
        assert interpolate_color(palette, -100, 0, 100) == "#000000"

    def test_clamp_high(self) -> None:
        palette = ["#000000", "#ffffff"]
        assert interpolate_color(palette, 200, 0, 100) == "#ffffff"

    def test_exact_low(self) -> None:
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        assert interpolate_color(palette, 0, 0, 2) == "#ff0000"

    def test_exact_high(self) -> None:
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        assert interpolate_color(palette, 2, 0, 2) == "#0000ff"

    def test_midpoint_interpolation(self) -> None:
        palette = ["#ff0000", "#0000ff"]  # red to blue
        result = interpolate_color(palette, 0.5, 0, 1)
        assert result == "#800080"  # midway in RGB: (255+0)//2=128


class TestSamplePalette:
    def test_n_zero(self) -> None:
        assert sample_palette(["#000"], 0) == []

    def test_n_one(self) -> None:
        result = sample_palette(["#ff0000", "#00ff00"], 1)
        assert result == ["#ff0000"]

    def test_n_one_reverse(self) -> None:
        result = sample_palette(["#ff0000", "#00ff00"], 1, reverse=True)
        assert result == ["#00ff00"]

    def test_n_equals_length(self) -> None:
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        result = sample_palette(palette, 3)
        assert len(result) == 3
        assert result[0] == "#ff0000"
        assert result[2] == "#0000ff"

    def test_n_greater_than_length(self) -> None:
        palette = ["#000000", "#ffffff"]
        result = sample_palette(palette, 5)
        assert len(result) == 5

    def test_reverse(self) -> None:
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        result = sample_palette(palette, 3, reverse=True)
        assert result == ["#0000ff", "#00ff00", "#ff0000"]
