"""Tests for NAIP aerial imagery fetcher service (Planetary Computer STAC)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from brewgis.workspace.services.naip_fetcher import _format_bbox_for_cache
from brewgis.workspace.services.naip_fetcher import _get_cog_url
from brewgis.workspace.services.naip_fetcher import download_naip_raster


class TestNAIPCacheKey:
    """Tests for cache key formatting."""

    def test_format_bbox_replaces_dots(self) -> None:
        """Cache key should replace dots with underscores."""
        key = _format_bbox_for_cache((-121.5, 38.5, -121.3, 38.7))
        assert "_" in key
        assert "." not in key

    def test_format_bbox_rounds_to_4_decimals(self) -> None:
        """Values should be rounded to 4 decimal places."""
        key = _format_bbox_for_cache((-121.56789, 38.56789, -121.3, 38.7))
        # Key contains all four values rounded to 4 decimals, dots replaced
        assert "5679" in key  # -121.5679 rounded to 4 decimals
        assert "3000" in key  # -121.3000


class TestGetCogUrl:
    """Tests for COG URL extraction from STAC features."""

    def test_extract_from_image_asset(self) -> None:
        """Should extract href from the 'image' asset."""
        feature = {"assets": {"image": {"href": "https://example.com/tile.tif"}}}
        assert _get_cog_url(feature) == "https://example.com/tile.tif"

    def test_returns_none_for_missing_assets(self) -> None:
        """Should return None when no assets exist."""
        assert _get_cog_url({}) is None

    def test_returns_none_for_empty_assets(self) -> None:
        """Should return None when assets has no image key."""
        feature = {"assets": {"thumbnail": {"href": "thumb.jpg"}}}
        result = _get_cog_url(feature)
        assert result is None


class TestDownloadNAIPRaster:
    """Tests for the NAIP download resolution function."""

    def test_cache_hit_returns_urls(self) -> None:
        """When cached URL file exists, read from cache without STAC query."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "brewgis.workspace.services.naip_fetcher._NAIP_CACHE_DIR",
                Path(tmpdir),
            ),
        ):
            cache_key = _format_bbox_for_cache((-121.5, 38.5, -121.3, 38.7))
            cache_path = Path(tmpdir) / f"{cache_key}_urls.txt"
            cache_path.write_text("https://example.com/tile.tif")

            result = download_naip_raster((-121.5, 38.5, -121.3, 38.7))
            assert result == "https://example.com/tile.tif"

    def test_cache_hit_multiple_urls(self) -> None:
        """Multiple cached URLs should be returned as a list."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "brewgis.workspace.services.naip_fetcher._NAIP_CACHE_DIR",
                Path(tmpdir),
            ),
        ):
            cache_key = _format_bbox_for_cache((-121.5, 38.5, -121.3, 38.7))
            cache_path = Path(tmpdir) / f"{cache_key}_urls.txt"
            cache_path.write_text(
                "https://example.com/tile1.tif\nhttps://example.com/tile2.tif"
            )
            result = download_naip_raster((-121.5, 38.5, -121.3, 38.7))
            assert isinstance(result, list)
            assert len(result) == 2

    def test_missing_stac_query_fails(self) -> None:
        """When no STAC tiles found and no cache, raise RuntimeError."""
        with (
            patch(
                "brewgis.workspace.services.naip_fetcher._find_naip_tiles",
                return_value=[],
            ),
            patch(
                "brewgis.workspace.services.naip_fetcher._NAIP_CACHE_DIR",
                Path(tempfile.mkdtemp()),
            ),
            pytest.raises(RuntimeError, match="No NAIP tiles found"),
        ):
            download_naip_raster((-121.5, 38.5, -121.3, 38.7))
