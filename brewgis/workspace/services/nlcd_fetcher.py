"""NLCD (National Land Cover Database) raster downloader.

Downloads NLCD land cover rasters via MRLC WCS and caches them
locally.  The S3 bucket ``mrlcdata`` was retired by MRLC in 2024,
so all downloads now go through the MRLC Geoserver WCS endpoint.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
import zlib
from pathlib import Path

import pyproj
import requests

logger = logging.getLogger(__name__)

_NLCD_CACHE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "planning"
_NLCD_CACHE_DIR = _NLCD_CACHE_ROOT / "nlcd"

_MRLC_WCS_URL = "https://www.mrlc.gov/geoserver/wcs"

# Well-known cache filenames — the Caller (management command or dlt
# pipeline) is responsible for downloading the raster to these paths
# *before* running the SQLMesh plan.  The DuckDB staging VIEW reads
# from these locations.
DEFAULT_LAND_COVER_PATH = _NLCD_CACHE_DIR / "nlcd_land_cover.tif"
DEFAULT_TREE_CANOPY_PATH = _NLCD_CACHE_DIR / "nlcd_tree_canopy.tif"


def download_nlcd_subset(  # noqa: PLR0913
    west: float,
    south: float,
    east: float,
    north: float,
    *,
    year: int = 2021,
    cache_path: Path | None = None,
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
        cache_path: Destination file path.  When not provided the file
            is stored at ``_DEFAULT_LAND_COVER_PATH``.
        refresh_cache: If True, delete cached file and re-download.
        source_crs: CRS of the input coordinates (e.g. ``"EPSG:4326"``).
            When provided and not EPSG:5070, coordinates are reprojected.
        coverage_id: WCS coverage identifier. Defaults to the NLCD land
            cover coverage for the given year.

    Returns:
        Path to cached GeoTIFF, or ``None`` on failure.
    """
    nlcd_native_crs = "EPSG:5070"

    if source_crs is not None and source_crs.upper() != nlcd_native_crs:
        transformer = pyproj.Transformer.from_crs(
            source_crs, nlcd_native_crs, always_xy=True
        )
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

    result_path = cache_path or DEFAULT_LAND_COVER_PATH
    if result_path.exists() and not refresh_cache:
        if _verify_cached_file(result_path):
            return str(result_path)

    if refresh_cache:
        result_path.unlink(missing_ok=True)

    _NLCD_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    response = requests.get(_MRLC_WCS_URL, params=params, timeout=300)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".tif") as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    shutil.move(tmp_path, str(result_path))
    logger.info("NLCD raster cached at %s", result_path)
    return str(result_path)


def download_nlcd_raster(
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2021,
    *,
    refresh_cache: bool = False,
    source_crs: str | None = None,
    tree_canopy: bool = False,
) -> str:
    """Download an NLCD land cover (or tree canopy) GeoTIFF subset.

    The caller **must** provide a *bbox* — the dead S3 CONUS fallback
    has been removed.  Use ``download_nlcd_subset`` for more control;
    this is a convenience wrapper that picks good defaults.

    When *tree_canopy* is True the raster is saved to
    ``_DEFAULT_TREE_CANOPY_PATH`` instead of ``_DEFAULT_LAND_COVER_PATH``
    so the DuckDB staging views can discover it.

    Args:
        bbox: Bounding box ``(west, south, east, north)`` in
            *source_crs* (or EPSG:5070 if None).  **Required.**
        year: NLCD year (default 2021).
        refresh_cache: If True, re-download.
        source_crs: CRS of the bbox coordinates.
        tree_canopy: If True, download tree canopy instead of land cover.

    Returns:
        Path to cached GeoTIFF, or ``None`` on failure.

    Raises:
        ValueError: if *bbox* is None.
    """
    if bbox is None:
        _msg = (
            "bbox is required — the S3 CONUS fallback was retired. "
            "Compute the bbox from parcel ST_Extent or pass it explicitly."
        )
        raise ValueError(_msg)

    west, south, east, north = bbox

    if tree_canopy:
        return download_nlcd_subset(
            west,
            south,
            east,
            north,
            year=year,
            cache_path=DEFAULT_TREE_CANOPY_PATH,
            refresh_cache=refresh_cache,
            source_crs=source_crs,
            coverage_id=f"mrlc_download__nlcd_tcc_conus_{year}_v2021-4",
        )

    return download_nlcd_subset(
        west,
        south,
        east,
        north,
        year=year,
        cache_path=DEFAULT_LAND_COVER_PATH,
        refresh_cache=refresh_cache,
        source_crs=source_crs,
    )


def download_nlcd_tree_canopy_raster(
    bbox: tuple[float, float, float, float] | None = None,
    year: int = 2016,
    *,
    refresh_cache: bool = False,
    source_crs: str | None = None,
) -> str:
    """Convenience wrapper — delegates to ``download_nlcd_raster(…, tree_canopy=True)``.

    Args:
        bbox: Required bounding box ``(west, south, east, north)``.
        year: NLCD tree canopy year (default 2016). Valid: 2011, 2016, 2019.
        refresh_cache: If True, re-download.
        source_crs: CRS of the bbox coordinates.

    Returns:
        Path to cached GeoTIFF.

    Raises:
        ValueError: if *bbox* is None.
    """
    return download_nlcd_raster(
        bbox=bbox,
        year=year,
        refresh_cache=refresh_cache,
        source_crs=source_crs,
        tree_canopy=True,
    )


def ensure_raster_cached(
    bbox: tuple[float, float, float, float],
    *,
    land_cover_year: int = 2021,
    tree_canopy_year: int | None = 2016,
    refresh_cache: bool = False,
    source_crs: str | None = None,
) -> tuple[str, str | None]:
    """Download both NLCD rasters to the well-known cache paths.

    Call this before running a SQLMesh plan that references the
    DuckDB staging models ``duckdb.staging.*``.

    Args:
        bbox: Bounding box in *source_crs*.
        land_cover_year: NLCD land cover year.
        tree_canopy_year: NLCD tree canopy year (None to skip).
        refresh_cache: If True, re-download.
        source_crs: CRS of the bbox.

    Returns:
        ``(land_cover_path, tree_canopy_path_or_None)``.
    """
    lc = download_nlcd_raster(
        bbox,
        year=land_cover_year,
        refresh_cache=refresh_cache,
        source_crs=source_crs,
    )
    tc = (
        download_nlcd_raster(
            bbox,
            year=tree_canopy_year,
            refresh_cache=refresh_cache,
            source_crs=source_crs,
            tree_canopy=True,
        )
        if tree_canopy_year is not None
        else None
    )
    return lc, tc


def _verify_cached_file(path: Path, expected_size: int | None = None) -> bool:
    """Verify a cached file exists and has positive size."""
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
    """Verify cached file size and CRC32 against companion files."""
    expected_size: int | None = None
    with contextlib.suppress(ValueError, OSError):
        expected_size = int(size_path.read_text().strip())

    if not _verify_cached_file(path, expected_size):
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
            return False

    return True
