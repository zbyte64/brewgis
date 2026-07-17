"""NAIP (National Agriculture Imagery Program) aerial imagery downloader.

Resolves NAIP 60cm RGBN imagery COG URLs by discovering available tiles
directly from Azure blob storage, using the official USDA NAIP quad
shapefile to identify quads overlapping the target bounding box.

Shapefile format: ca_naip22qq (CA NAIP 2022 quarter-quad grid), available
from the USDA Aerial Photography Field Office. Each record corresponds to
a single NAIP quarter-quad corner tile.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas as gpd

from xml.etree import ElementTree as ET

import geopandas as gpd
import requests
from shapely.geometry import box

logger = logging.getLogger(__name__)

_CACHE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "planning"
_NAIP_CACHE_DIR = _CACHE_ROOT / "naip"
_COG_CACHE_DIR = _CACHE_ROOT / "cog"
_AZURE_NAIP_BASE = "https://naipeuwest.blob.core.windows.net/naip"
_NAIP_YEAR = 2022
_QUAD_SHAPEFILE = _CACHE_ROOT / "ca_naip22qq"
_AZURE_LIST_TIMEOUT = 15

# Compiled regex to extract base quad (first 5 digits) from NAIP tile filename
# e.g. m_3812118_nw_10_060_20220709.tif → 38121
_RE_TILE_QUAD = re.compile(r"m_(\d{5})\d\d_\w+_\d+_\d+_\d[\d_]*\.tif$")


def _load_quad_shapefile() -> gpd.GeoDataFrame:
    """Load the CA NAIP quarter-quad shapefile.

    Returns:
        GeoDataFrame with one row per quarter-quad corner tile.
    """
    path = _QUAD_SHAPEFILE
    gdf = gpd.read_file(str(path))
    if gdf.crs is not None and gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def _overlapping_base_quads(
    bbox: tuple[float, float, float, float],
) -> set[str]:
    """Find NAIP base quads whose quarter-quad tiles overlap ``bbox``.

    Uses the USDA shapefile to perform a spatial filter, then extracts
    the base quad (first 5 digits of the tile filename).

    Returns:
        Set of 5-digit base quad strings (e.g. ``{"38121"}``).
    """
    quads = _load_quad_shapefile()
    search_box = box(*bbox)
    mask = quads.intersects(search_box)
    overlapping = quads[mask]

    base_quads: set[str] = set()
    for fn in overlapping["FileName"]:
        m = _RE_TILE_QUAD.match(str(fn))
        if m:
            base_quads.add(m.group(1))
    return base_quads


def _list_quad_tiles(base_quad: str, year: int) -> list[str]:
    """List NAIP .tif COG URLs for one USGS base quad in a specific year."""
    prefix = f"v002/ca/{year}/ca_060cm_{year}/{base_quad}/"
    list_url = (
        f"{_AZURE_NAIP_BASE}?restype=container&comp=list"
        f"&prefix={prefix}&maxresults=5000"
    )
    try:
        resp = requests.get(list_url, timeout=_AZURE_LIST_TIMEOUT)
        if resp.status_code != 200:  # noqa: PLR2004
            return []
        root = ET.fromstring(resp.content)  # noqa: S314
        urls: list[str] = []
        for blob in root.findall(".//Blob"):
            name = blob.find("Name").text
            if not name.endswith(".tif"):
                continue
            urls.append(f"{_AZURE_NAIP_BASE}/{name}")
    except Exception:  # noqa: BLE001
        return []
    else:
        return urls


def _discover_naip_tiles_from_azure(
    bbox: tuple[float, float, float, float],
    year: int = _NAIP_YEAR,
) -> list[str]:
    """Discover NAIP COG URLs from Azure blob storage for the given bbox.

    Uses the official USDA NAIP quarter-quad shapefile to identify which
    USGS quads overlap the bounding box, then lists available .tif files
    for each quad on Azure blob storage.

    Returns:
        List of COG URLs for rasterio VSICurl access.
    """
    base_quads = _overlapping_base_quads(bbox)
    if not base_quads:
        return []

    logger.info("Azure discovery: %d base quad(s) overlap bbox", len(base_quads))

    all_urls: list[str] = []
    seen: set[str] = set()
    for quad in sorted(base_quads):
        urls = _list_quad_tiles(quad, year)
        for url in urls:
            if url not in seen:
                seen.add(url)
                all_urls.append(url)
        logger.info("  Quad %s: %d tile(s)", quad, len(urls))

    logger.info(
        "Azure discovery: %d total COG URL(s) from %d quad(s)",
        len(all_urls),
        len(base_quads),
    )
    return all_urls


def _format_bbox_for_cache(bbox: tuple[float, float, float, float]) -> str:
    """Format bbox rounded to 4 decimal places for stable cache keys."""
    west, south, east, north = bbox
    raw = f"{west:.4f}_{south:.4f}_{east:.4f}_{north:.4f}"
    return raw.replace(".", "_")


def download_naip_raster(
    bbox: tuple[float, float, float, float],
    *,
    year: int = _NAIP_YEAR,
    refresh_cache: bool = False,
) -> str | list[str]:
    """Resolve NAIP imagery covering the given bbox to COG URL(s).

    Discovers tiles directly from Azure blob storage using the USDA NAIP
    quarter-quad shapefile. URLs are cached as a text file for reuse.

    Args:
        bbox: Bounding box ``(west, south, east, north)`` in EPSG:4326.
        year: NAIP acquisition year.
        refresh_cache: If True, re-discover and re-cache.

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

    urls = _discover_naip_tiles_from_azure(bbox, year=year)
    if not urls:
        msg = f"No NAIP tiles found for bbox {bbox}"
        raise RuntimeError(msg)

    cache_path.write_text("\n".join(urls))
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


def download_cog_to_cache(cog_url: str) -> Path:
    """Download a single COG tile to a local cache path under the project root.

    Uses a SHA-256 hash of the URL as the cache key, so the same URL always
    resolves to the same local file. Cache hits return the existing path
    without a network request.

    Args:
        cog_url: URL of the COG tile to download.

    Returns:
        Local path to the cached COG file.

    Raises:
        requests.HTTPError: If the download fails.
        OSError: If disk is full or rename fails.
    """
    cache_path = (
        _COG_CACHE_DIR / f"{hashlib.sha256(cog_url.encode()).hexdigest()[:24]}.tif"
    )
    if cache_path.exists():
        return cache_path

    _COG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(".tif.tmp")

    with requests.get(cog_url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with tmp_path.open("wb") as f:
            f.writelines(r.iter_content(chunk_size=131_072))

    tmp_path.replace(cache_path)
    logger.info("Cached COG: %s -> %s", cog_url.rsplit("/", 1)[-1], cache_path)
    return cache_path


def download_cog_tiles(cog_urls: list[str]) -> list[Path]:
    """Download multiple COG tiles to local cache.

    Wraps :func:`download_cog_to_cache` for batch use. For each URL,
    returns the local path (from cache or fresh download).

    Args:
        cog_urls: List of COG URLs to cache locally.

    Returns:
        List of local paths in the same order as the input URLs.
    """
    paths: list[Path] = []
    for i, url in enumerate(cog_urls):
        path = download_cog_to_cache(url)
        paths.append(path)
        logger.info(
            "Caching COG tile %d/%d: %s", i + 1, len(cog_urls), url.rsplit("/", 1)[-1]
        )
    return paths
