"""NAIP (National Agriculture Imagery Program) aerial imagery downloader.

Resolves NAIP 60cm RGBN imagery COG URLs by discovering available tiles
directly from Azure blob storage, using the official USDA NAIP quad
shapefile to identify the individual quarter-quad tiles overlapping the
target bounding box — a base-quad listing holds every tile of that quad,
only a small fraction of which the bbox needs.

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

# NAIP tile filenames — the first 12 characters name the quarter-quad
# (``m_<7-digit tile id>_<quadrant>``), which stays stable across acquisition
# dates. The USDA shapefile spells a tile ``m_3812118_nw_10_060_20220709_20220909.tif``
# while the Azure blob drops the second date, so one pattern matches both.
_RE_TILE_NAME = re.compile(r"^(?P<stem>m_\d{7}_[a-z]{2})_\d+_\d+_\d[\d_]*\.tif$")


def _tile_stem(filename: str) -> str | None:
    """Quarter-quad tile stem of a NAIP tile filename, or None if not one.

    Returns:
        ``m_3812118_nw`` for a NAIP quarter-quad tile filename, else ``None``.
    """
    match = _RE_TILE_NAME.match(filename)
    return match["stem"] if match else None


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


def _overlapping_tile_stems(
    bbox: tuple[float, float, float, float],
) -> dict[str, set[str]]:
    """Find the NAIP quarter-quad tiles whose footprint intersects ``bbox``.

    Uses the USDA shapefile to perform a spatial filter, then keeps each
    surviving tile's stem, grouped by the base quad its blob lives under.

    Returns:
        Mapping of 5-digit base quad to the set of tile stems inside it that
        overlap ``bbox`` (e.g. ``{"38121": {"m_3812118_nw"}}``).
    """
    quads = _load_quad_shapefile()
    search_box = box(*bbox)
    overlapping = quads[quads.intersects(search_box)]

    stems: dict[str, set[str]] = {}
    for fn in overlapping["FileName"]:
        stem = _tile_stem(str(fn))
        if stem is None:
            continue
        stems.setdefault(stem[2:7], set()).add(stem)
    return stems


def _list_quad_tiles(base_quad: str, year: int) -> list[str]:
    """List NAIP .tif COG URLs for one USGS base quad in a specific year.

    Follows the listing's ``NextMarker`` so a quad directory larger than one
    page comes back in full rather than silently truncated.

    Returns:
        Every ``.tif`` blob URL under the quad, in listing order.
    """
    prefix = f"v002/ca/{year}/ca_060cm_{year}/{base_quad}/"
    urls: list[str] = []
    marker: str | None = None
    while True:
        params: dict[str, str | int] = {
            "restype": "container",
            "comp": "list",
            "prefix": prefix,
            "maxresults": 5000,
        }
        if marker:
            params["marker"] = marker
        resp = requests.get(
            _AZURE_NAIP_BASE, params=params, timeout=_AZURE_LIST_TIMEOUT
        )
        if resp.status_code != 200:  # noqa: PLR2004
            msg = (
                f"Azure blob listing failed for quad {base_quad}: "
                f"HTTP {resp.status_code}"
            )
            raise RuntimeError(msg)
        root = ET.fromstring(resp.content)  # noqa: S314
        for blob in root.findall(".//Blob"):
            name_blob = blob.find("Name")
            name = name_blob.text if name_blob is not None else None
            if name and name.endswith(".tif"):
                urls.append(f"{_AZURE_NAIP_BASE}/{name}")

        next_marker = root.find(".//NextMarker")
        marker = next_marker.text if next_marker is not None else None
        if not marker:
            return urls


def _discover_naip_tiles_from_azure(
    bbox: tuple[float, float, float, float],
    year: int = _NAIP_YEAR,
) -> list[str]:
    """Discover NAIP COG URLs from Azure blob storage for the given bbox.

    Uses the official USDA NAIP quarter-quad shapefile to identify which
    tiles overlap the bounding box, then keeps only those tiles out of each
    base quad's Azure listing — a quad directory holds every tile of the
    quad (all quadrants, all acquisition dates), and a given bbox touches
    only a fraction of them.

    Returns:
        List of COG URLs for rasterio VSICurl access.
    """
    wanted = _overlapping_tile_stems(bbox)
    if not wanted:
        return []

    logger.info("Azure discovery: %d base quad(s) overlap bbox", len(wanted))

    all_urls: list[str] = []
    seen: set[str] = set()
    for quad in sorted(wanted):
        quad_stems = wanted[quad]
        matched: set[str] = set()
        for url in _list_quad_tiles(quad, year):
            stem = _tile_stem(url.rsplit("/", 1)[-1])
            if stem is None or stem not in quad_stems or url in seen:
                continue
            seen.add(url)
            matched.add(stem)
            all_urls.append(url)
        logger.info(
            "  Quad %s: %d of %d overlapping tile(s) listed",
            quad,
            len(matched),
            len(quad_stems),
        )
        missing = quad_stems - matched
        if missing:
            logger.warning(
                "  Quad %s: %d overlapping tile(s) absent from Azure listing: %s",
                quad,
                len(missing),
                sorted(missing),
            )

    logger.info(
        "Azure discovery: %d total COG URL(s) from %d quad(s)",
        len(all_urls),
        len(wanted),
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
