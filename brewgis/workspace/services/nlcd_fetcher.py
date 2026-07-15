"""NLCD (National Land Cover Database) raster downloader.

Downloads NLCD land cover rasters via MRLC WCS (subset) or S3 (full
CONUS) and caches them locally.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import zlib
from pathlib import Path

import pyproj
import requests

logger = logging.getLogger(__name__)

# NLCD download base URL
_NLCD_BASE_URL = "https://s3-us-west-2.amazonaws.com/mrlcdata"
_NLCD_YEAR = 2021
_CACHE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "planning"
_NLCD_CACHE_DIR = _CACHE_ROOT / "nlcd"

_MRLC_WCS_URL = "https://www.mrlc.gov/geoserver/wcs"


def _download_nlcd_subset(  # noqa: PLR0913
    west: float,
    south: float,
    east: float,
    north: float,
    year: int = 2021,
    cache_dir: Path = _NLCD_CACHE_DIR,
    *,
    refresh_cache: bool = False,
    source_crs: str | None = None,
    coverage_id: str | None = None,
) -> str:
    """Download an NLCD bounding-box subset via MRLC WCS.

    The WCS coverage is stored in EPSG:5070 (USA Contiguous Albers
    Equal Area Conic).  Coordinates are reprojected to EPSG:5070
    when *source_crs* is provided.

    Args:
        west: Western bound in *source_crs* (or EPSG:5070 if None).
        south: Southern bound in *source_crs* (or EPSG:5070 if None).
        east: Eastern bound in *source_crs* (or EPSG:5070 if None).
        north: Northern bound in *source_crs* (or EPSG:5070 if None).
        year: NLCD year (default 2021).
        cache_dir: Directory for cached GeoTIFFs.
        refresh_cache: If True, delete cached file and re-download.
        source_crs: CRS of the input coordinates (e.g. ``"EPSG:4326"``).
            When provided and not EPSG:5070, coordinates are reprojected.
        coverage_id: WCS coverage identifier. Defaults to the NLCD land
            cover coverage for the given year.

    Returns:
        Path to cached GeoTIFF, or None on failure.
        The GeoTIFF is clipped to the specified bounding box.
    """
    nlcd_native_crs = "EPSG:5070"

    # Reproject to the coverage native CRS if needed
    if source_crs is not None and source_crs.upper() != nlcd_native_crs:
        transformer = pyproj.Transformer.from_crs(
            source_crs, nlcd_native_crs, always_xy=True
        )
        # Transform all four corners; Albers conic projection can invert
        # the Y-axis ordering vs latitude, so take the axis-aligned envelope.
        corners = [
            transformer.transform(west, south),
            transformer.transform(east, south),
            transformer.transform(west, north),
            transformer.transform(east, north),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        west, east = min(xs), max(xs)
        south, north = min(ys), max(ys)

    if coverage_id is None:
        coverage_id = f"mrlc_download__NLCD_{year}_Land_Cover_L48"

    params: dict[str, str | list[str]] = {
        "service": "WCS",
        "version": "2.0.1",
        "request": "GetCoverage",
        "CoverageId": coverage_id,
        "subset": [f"X({west},{east})", f"Y({south},{north})"],
        "format": "image/geotiff",
    }

    cache_key = f"nlcd_{year}_{west}_{south}_{east}_{north}".replace(".", "_")
    cache_path = cache_dir / f"{cache_key}.tif"

    if cache_path.exists() and not refresh_cache:
        if _verify_cached_file(cache_path):
            return str(cache_path)

    if refresh_cache:
        cache_path.unlink(missing_ok=True)

    response = requests.get(_MRLC_WCS_URL, params=params, timeout=300)
    response.raise_for_status()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    return str(cache_path)


def _verify_cached_file(path: Path, expected_size: int | None = None) -> bool:
    """Verify a cached file exists, has positive size, and optionally matches expected size.

    Returns True if file appears valid.
    Logs a warning and returns False for corrupt/missing files.
    """
    if not path.exists():
        return False
    if path.stat().st_size == 0:
        logger.warning("Cached file %s is empty, removing", path)
        path.unlink(missing_ok=True)
        return False
    if expected_size is not None and path.stat().st_size != expected_size:
        logger.warning(
            "Cached file %s size mismatch: expected %d, got %d",
            path,
            expected_size,
            path.stat().st_size,
        )
        path.unlink(missing_ok=True)
        return False
    return True


def _verify_cached_bytes(path: Path, size_path: Path, crc32_path: Path) -> bool:
    """Verify cached file size and CRC32 against companion files.

    Returns True if verification passes and the file can be used.
    On failure, removes the corrupt file and returns False so the
    caller re-downloads.
    """
    expected_size: int | None = None
    with contextlib.suppress(ValueError, OSError):
        expected_size = int(size_path.read_text().strip())

    if not _verify_cached_file(path, expected_size):
        path.unlink(missing_ok=True)
        return False

    if crc32_path.exists():
        try:
            expected_crc = int(crc32_path.read_text().strip())
            actual_crc = zlib.crc32(path.read_bytes())
            if actual_crc != expected_crc:
                logger.warning(
                    "Cached file %s CRC32 mismatch: expected %d, got %d",
                    path,
                    expected_crc,
                    actual_crc,
                )
                path.unlink(missing_ok=True)
                return False
        except (ValueError, OSError) as exc:
            logger.warning("Failed to read CRC32 for %s: %s", path, exc)
            path.unlink(missing_ok=True)
            return False

    return True


def download_nlcd_raster(
    bbox: tuple[float, float, float, float] | None = None,
    year: int = _NLCD_YEAR,
    *,
    refresh_cache: bool = False,
    source_crs: str | None = None,
) -> str:
    """Download the NLCD land cover raster.

    When a bounding box is provided, uses the MRLC WCS endpoint to
    download only the subset covering that area (much faster for
    county-sized analyses).  Falls back to the full CONUS download
    (S3) when bbox is ``None``.

    Cached files have companion .size and .crc32 files for integrity
    verification. On verification failure the corrupt file is removed
    and re-downloaded.

    Args:
        bbox: Optional bounding box ``(west, south, east, north)``.
            When provided, uses WCS subset download.  Coordinates are
            interpreted in *source_crs* (or EPSG:5070 if None).
        year: NLCD year (default 2021).
        refresh_cache: If True, delete cached files and re-download.
        source_crs: CRS of the bbox coordinates.  Passed through to
            the WCS subset downloader.

    Returns:
        Path to the (potentially clipped) GeoTIFF, or ``None`` if
        download fails.
    """
    if bbox is not None:
        west, south, east, north = bbox
        return _download_nlcd_subset(
            west,
            south,
            east,
            north,
            year=year,
            refresh_cache=refresh_cache,
            source_crs=source_crs,
        )

    # ── Fallback: full CONUS download (S3) ──────────────────────
    cache_dir = _NLCD_CACHE_DIR / str(year)
    cache_dir.mkdir(parents=True, exist_ok=True)

    raster_name = f"nlcd_{year}_land_cover_l48_20230630.img"
    raster_path = cache_dir / raster_name
    size_path = cache_dir / f"{raster_name}.size"
    crc32_path = cache_dir / f"{raster_name}.crc32"

    if refresh_cache:
        for p in [raster_path, size_path, crc32_path]:
            p.unlink(missing_ok=True)

    if not raster_path.exists() or not _verify_cached_bytes(
        raster_path, size_path, crc32_path
    ):
        url = f"{_NLCD_BASE_URL}/nlcd/{year}/land_cover/l48/{raster_name}"
        logger.info("Downloading NLCD CONUS raster from %s ...", url)
        response = requests.get(url, timeout=600)
        response.raise_for_status()
        import shutil

        with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        shutil.move(tmp_path, str(raster_path))
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            size_path.write_text(content_length)
        crc32_path.write_text(str(zlib.crc32(response.content)))
        logger.info("NLCD raster cached at %s", raster_path)

    return str(raster_path)


def download_nlcd_tree_canopy_raster(
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2016,
    *,
    refresh_cache: bool = False,
    source_crs: str | None = None,
) -> str:
    """Download the NLCD Tree Canopy Cover (USFS) raster.

    When a bounding box is provided, uses the MRLC WCS endpoint to
    download only the subset covering that area (much faster for
    county-sized analyses).  Falls back to the full CONUS download
    (S3) when bbox is ``None``.

    The tree canopy product covers 0-100% continuous values at 30m
    resolution, available for 2011, 2016, and 2019 vintages.

    Cached files have companion .size and .crc32 files for integrity
    verification. On verification failure the corrupt file is removed
    and re-downloaded.

    Args:
        bbox: Optional bounding box ``(west, south, east, north)``.
            When provided, uses WCS subset download.  Coordinates are
            interpreted in *source_crs* (or EPSG:5070 if None).
        year: NLCD tree canopy year (default 2016). Valid: 2011, 2016, 2019.
        refresh_cache: If True, delete cached files and re-download.
        source_crs: CRS of the bbox coordinates.  Passed through to
            the WCS subset downloader.

    Returns:
        Path to the (potentially clipped) GeoTIFF, or ``None`` if
        download fails.
    """
    if bbox is not None:
        west, south, east, north = bbox
        return _download_nlcd_subset(
            west,
            south,
            east,
            north,
            year=year,
            refresh_cache=refresh_cache,
            source_crs=source_crs,
            coverage_id=f"mrlc_download__nlcd_tcc_conus_{year}_v2021-4",
        )

    # ── Fallback: full CONUS download (S3) ──────────────────────
    cache_dir = _NLCD_CACHE_DIR / str(year) / "tree_canopy"
    cache_dir.mkdir(parents=True, exist_ok=True)

    raster_name = f"nlcd_{year}_tree_canopy_l48.img"
    raster_path = cache_dir / raster_name
    size_path = cache_dir / f"{raster_name}.size"
    crc32_path = cache_dir / f"{raster_name}.crc32"

    if refresh_cache:
        for p in [raster_path, size_path, crc32_path]:
            p.unlink(missing_ok=True)

    if not raster_path.exists() or not _verify_cached_bytes(
        raster_path, size_path, crc32_path
    ):
        url = f"{_NLCD_BASE_URL}/nlcd/{year}/tree_canopy/l48/{raster_name}"
        logger.info("Downloading NLCD Tree Canopy CONUS raster from %s ...", url)
        response = requests.get(url, timeout=600)
        response.raise_for_status()
        import shutil

        with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        shutil.move(tmp_path, str(raster_path))
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            size_path.write_text(content_length)
        crc32_path.write_text(str(zlib.crc32(response.content)))
        logger.info("NLCD Tree Canopy raster cached at %s", raster_path)

    return str(raster_path)
