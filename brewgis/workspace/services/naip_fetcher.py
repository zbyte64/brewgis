"""NAIP (National Agriculture Imagery Program) aerial imagery downloader.

Resolves NAIP 60cm RGBN imagery COG URLs via Microsoft Planetary Computer
STAC API. COGs are served from Azure Blob Storage (public, no auth) and read
via rasterio VSICurl for efficient partial-window access.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)

_NAIP_CACHE_DIR = Path.home() / ".cache" / "brewgis" / "naip"
_STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
_NAIP_YEAR = 2024
_STAC_SEARCH_LIMIT = 500


def _find_naip_tiles(bbox: tuple[float, float, float, float]) -> list[dict]:
    """Query Planetary Computer STAC for NAIP tiles covering the given bbox.

    Args:
        bbox: (west, south, east, north) in EPSG:4326.

    Returns:
        List of STAC feature dicts, each with an ``assets.image.href`` COG URL.
    """
    import requests

    west, south, east, north = bbox
    params = {
        "collections": "naip",
        "bbox": f"{west},{south},{east},{north}",
        "limit": _STAC_SEARCH_LIMIT,
    }
    response = requests.get(f"{_STAC_API_URL}/search", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    features = data.get("features", [])

    # Parse naip:year (returned as string by API, e.g. '2022') and filter
    # to the target year. If no tiles match the target year, deduplicate by
    # USGS quad (extracted from tile ID) keeping only the most recent year
    # per quad, so we process one tile per area instead of multiple years
    # of the same coverage.
    def _tile_year(f: dict) -> int:
        y = f.get("properties", {}).get("naip:year")
        if y is not None:
            return int(y)
        # Fallback: extract year from datetime or tile ID
        dt = f.get("properties", {}).get("datetime", "")
        if dt:
            return int(dt[:4])
        parts = f.get("id", "").split("_")
        for p in reversed(parts):
            if p.isdigit() and len(p) >= _year_len:
                return int(p[:_year_len])
        return 0

    _year_len = 4
    _quad_index = 2
    _min_len = 3

    target = int(_NAIP_YEAR)
    year_features = [f for f in features if _tile_year(f) == target]
    if year_features:
        return year_features

    # No tiles match the target year. Deduplicate by quad, keeping the
    # most recent year for each. The quad is the 3rd underscore-delimited
    # component of the tile ID (e.g. '3812147' in
    # ca_m_3812147_sw_10_060_20220621).
    seen_quads: dict[str, dict] = {}
    for f in features:
        parts = f.get("id", "").split("_")
        if len(parts) < _quad_index + 1:
            continue
        quad = parts[_quad_index]
        existing = seen_quads.get(quad)
        if existing is None or _tile_year(f) > _tile_year(existing):
            seen_quads[quad] = f
    return list(seen_quads.values())


def _get_cog_url(tile: dict) -> str | None:
    """Extract the COG asset URL from a STAC feature."""
    assets = tile.get("assets", {})
    image = assets.get("image", {})
    href = image.get("href")
    if href:
        return href
    for key in ("cog", "geotiff"):
        img = assets.get(key, {})
        if img.get("href"):
            return img["href"]
    return None


def _format_bbox_for_cache(bbox: tuple[float, float, float, float]) -> str:
    """Format bbox rounded to 4 decimal places for stable cache keys."""
    west, south, east, north = bbox
    raw = f"{west:.4f}_{south:.4f}_{east:.4f}_{north:.4f}"
    return raw.replace(".", "_")


def download_naip_raster(
    bbox: tuple[float, float, float, float],
    *,
    year: int = _NAIP_YEAR,  # noqa: ARG001
    refresh_cache: bool = False,
) -> str | list[str]:
    """Resolve NAIP imagery covering the given bbox to COG URL(s).

    Returns a COG URL (or list of URLs) that can be opened directly via
    ``rasterio.open(url)`` using VSICurl — no local file download needed.

    URLs are cached as a text file so re-runs with the same bbox skip
    the STAC query.

    Args:
        bbox: Bounding box ``(west, south, east, north)`` in EPSG:4326.
        year: NAIP year (ignored — PC uses latest available).
        refresh_cache: If True, re-query STAC.

    Returns:
        A COG URL string, or list of COG URLs if multiple tiles needed.

    Raises:
        RuntimeError: If no NAIP tiles found for the bbox.
    """
    _NAIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = _format_bbox_for_cache(bbox)
    cache_path = _NAIP_CACHE_DIR / f"{cache_key}_urls.txt"

    if cache_path.exists() and not refresh_cache:
        urls = cache_path.read_text().strip().splitlines()
        logger.info("NAIP cache hit: %d COG URL(s)", len(urls))
        return urls if len(urls) > 1 else urls[0]

    tiles = _find_naip_tiles(bbox)
    if not tiles:
        msg = f"No NAIP tiles found for bbox {bbox}"
        raise RuntimeError(msg)

    # Collect unique COG URLs from all tiles
    urls: list[str] = []
    seen: set[str] = set()
    for tile in tiles:
        url = _get_cog_url(tile)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    if not urls:
        msg = f"No COG asset URLs found in NAIP tiles for bbox {bbox}"
        raise RuntimeError(msg)

    cache_path.write_text("\n".join(urls))
    logger.info("Cached %d NAIP COG URL(s)", len(urls))
    return urls if len(urls) > 1 else urls[0]


def download_naip_for_parcels(
    gdf: gpd.GeoDataFrame,
    *,
    year: int = _NAIP_YEAR,
) -> str | list[str]:
    """Resolve NAIP COG URL(s) covering the full parcel extent.

    Args:
        gdf: GeoDataFrame of parcel geometries (any CRS).
        year: NAIP year.

    Returns:
        COG URL (single) or list of COG URLs for rasterio VSICurl access.

    Raises:
        RuntimeError: If no NAIP tiles found.
    """
    gdf_4326 = gdf.to_crs("EPSG:4326") if gdf.crs is not None else gdf
    west, south, east, north = gdf_4326.total_bounds
    bbox = (west, south, east, north)

    return download_naip_raster(bbox, year=year)
