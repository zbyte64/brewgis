"""NLCD (National Land Cover Database) land cover data fetcher.

Downloads NLCD land cover rasters and computes zonal statistics per parcel
for land use classification and impervious surface fraction.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import requests

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)

# NLCD download base URL
_NLCD_BASE_URL = "https://s3-us-west-2.amazonaws.com/mrlcdata"
_NLCD_YEAR = 2021
_NLCD_CACHE_DIR = Path.home() / ".cache" / "brewgis" / "nlcd"

# NLCD land cover classes mapped to development categories
# See https://www.mrlc.gov/data/legends/national-land-cover-database-2021-nlcd2021-legend
_NLCD_URBAN_CLASSES = frozenset({21, 22, 23, 24})  # Developed
_NLCD_AGRICULTURE_CLASSES = frozenset({81, 82})  # Pasture/Hay, Cultivated Crops
_NLCD_BARREN_CLASSES = frozenset({31})  # Barren
_NLCD_FOREST_CLASSES = frozenset({41, 42, 43})  # Deciduous, Evergreen, Mixed
_NLCD_SHRUB_CLASSES = frozenset({51, 52})  # Shrub/Scrub
_NLCD_HERBACEOUS_CLASSES = frozenset({71, 72, 73, 74})  # Herbaceous
_NLCD_WATER_CLASSES = frozenset({11, 12})  # Open Water, Perennial Ice/Snow
_NLCD_WETLAND_CLASSES = frozenset({90, 95})  # Woody Wetlands, Emergent Herbaceous Wetlands


def _nlcd_majority_class(zonal_result: np.ndarray | None) -> str:
    """Map the majority NLCD class to a land development category.

    Args:
        zonal_result: Array of NLCD pixel values for one parcel.
            ``None`` or empty when no data is available.

    Returns:
        One of ``"urban"``, ``"agricultural"``, ``"industrial"``,
        ``"natural"``, or ``"unknown"``.
    """
    if zonal_result is None or len(zonal_result) == 0:
        return "unknown"

    # Find majority class
    values = zonal_result[~np.isnan(zonal_result)]
    if len(values) == 0:
        return "unknown"

    unique, counts = np.unique(values, return_counts=True)
    majority = unique[np.argmax(counts)]
    majority = int(majority)

    if majority in _NLCD_URBAN_CLASSES:
        if majority == 24:  # High intensity → likely industrial/commercial
            return "industrial"
        return "urban"
    if majority in _NLCD_AGRICULTURE_CLASSES:
        return "agricultural"
    if majority in _NLCD_BARREN_CLASSES:
        return "industrial"
    if majority in (
        _NLCD_FOREST_CLASSES | _NLCD_SHRUB_CLASSES | _NLCD_HERBACEOUS_CLASSES
    ):
        return "natural"
    return "unknown"


def _estimate_nlcd_impervious_fraction(
    zonal_result: np.ndarray | None,
) -> float:
    """Estimate impervious surface fraction from NLCD pixels.

    Uses NLCD developed class intensities:
        - 21 (Developed, Open Space): ~10% impervious
        - 22 (Developed, Low Intensity): ~30% impervious
        - 23 (Developed, Medium Intensity): ~60% impervious
        - 24 (Developed, High Intensity): ~85% impervious

    Args:
        zonal_result: Array of NLCD pixel values for one parcel.

    Returns:
        Impervious fraction (0.0 to 1.0). 0.0 when no data.
    """
    if zonal_result is None or len(zonal_result) == 0:
        return 0.0

    values = zonal_result[~np.isnan(zonal_result)]
    if len(values) == 0:
        return 0.0

    # Approximate impervious fractions per NLCD class
    impervious_map = {
        21: 0.10,
        22: 0.30,
        23: 0.60,
        24: 0.85,
        31: 0.50,  # Barren
    }
    total_impervious = 0.0
    for val in values:
        total_impervious += impervious_map.get(int(val), 0.0)

    return total_impervious / len(values)



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
    bbox: tuple[float, float, float, float],
    year: int = _NLCD_YEAR,
    *,
    refresh_cache: bool = False,
) -> str | None:
    """Download the NLCD land cover raster for a given bounding box.

    Downloads the CONUS-wide NLCD raster if not already cached, then
    extracts the bounding box subset.

    Cached files have companion .size and .crc32 files for integrity
    verification. On verification failure the corrupt file is removed
    and re-downloaded.

    Args:
        bbox: Bounding box ``(min_x, min_y, max_x, max_y)`` in EPSG:4326.
        year: NLCD year (default 2021).
        refresh_cache: If True, delete cached files and re-download.

    Returns:
        Path to the clipped GeoTIFF, or ``None`` if download fails.
    """
    cache_dir = _NLCD_CACHE_DIR / str(year)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # NLCD CONUS raster file pattern
    raster_name = f"nlcd_{year}_land_cover_l48_20230630.img"
    raster_path = cache_dir / raster_name
    size_path = cache_dir / f"{raster_name}.size"
    crc32_path = cache_dir / f"{raster_name}.crc32"

    if refresh_cache:
        for p in [raster_path, size_path, crc32_path]:
            p.unlink(missing_ok=True)

    if not raster_path.exists() or not _verify_cached_bytes(raster_path, size_path, crc32_path):
        url = f"{_NLCD_BASE_URL}/nlcd/{year}/land_cover/l48/{raster_name}"
        logger.info("Downloading NLCD CONUS raster from %s ...", url)
        try:
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
        except requests.RequestException as exc:
            logger.warning("Failed to download NLCD raster: %s", exc)
            return None

    # Clip to bounding box using gdalwarp or rasterio
    clipped_path = (
        cache_dir / f"clip_{bbox[0]:.3f}_{bbox[1]:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}.tif"
    )
    if clipped_path.exists():
        return str(clipped_path)

    try:
        import subprocess
        cmd = [
            "gdalwarp",
            "-te", str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
            "-te_srs", "EPSG:4326",
            "-of", "GTiff",
            str(raster_path),
            str(clipped_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        return str(clipped_path)
    except Exception as exc:
        logger.warning("Failed to clip NLCD raster: %s", exc)
        return None


def compute_nlcd_zonal_stats(
    parcels: gpd.GeoDataFrame,
    bbox: tuple[float, float, float, float],
    year: int = _NLCD_YEAR,
) -> gpd.GeoDataFrame:
    """Compute NLCD zonal statistics for each parcel.

    Args:
        parcels: Parcels GeoDataFrame with polygon geometry in EPSG:4326.
        bbox: Bounding box ``(min_x, min_y, max_x, max_y)`` in EPSG:4326.
        year: NLCD year (default 2021).

    Returns:
        Parcels with ``land_development_category`` and
        ``impervious_fraction`` columns populated.
    """
    raster_path = download_nlcd_raster(bbox, year)
    if raster_path is None:
        logger.warning("NLCD raster not available; using defaults")
        parcels["land_development_category"] = parcels.get(
            "land_development_category", pd.Series(index=parcels.index)
        ).fillna("urban")
        parcels["impervious_fraction"] = 0.0
        return parcels

    try:
        import rasterio
        from rasterio.mask import mask
        from shapely.geometry import mapping
    except ImportError:
        logger.warning(
            "rasterio not available; install with: pip install rasterio"
        )
        parcels["land_development_category"] = parcels.get(
            "land_development_category", pd.Series(index=parcels.index)
        ).fillna("urban")
        parcels["impervious_fraction"] = 0.0
        return parcels

    with rasterio.open(raster_path) as src:
        categories: list[str] = []
        impervious: list[float] = []

        for _, row in parcels.iterrows():
            geom = row.geometry
            if geom is None:
                categories.append("unknown")
                impervious.append(0.0)
                continue

            try:
                out_image, _ = mask(src, [mapping(geom)], crop=True, nodata=0)
                pixels = out_image[0]
                cat = _nlcd_majority_class(pixels)
                imp = _estimate_nlcd_impervious_fraction(pixels)
                categories.append(cat)
                impervious.append(imp)
            except Exception as exc:
                logger.debug("Zonal stats failed for parcel: %s", exc)
                categories.append("unknown")
                impervious.append(0.0)

    parcels["land_development_category"] = categories
    parcels["impervious_fraction"] = impervious
    return parcels


def classify_land_development(
    assessor_use_code: str | None = None,
    nlcd_majority: str | None = None,
) -> str:
    """Classify a parcel's land development category.

    Strategy (least-effort-first):
        1. Assessor use code → classification rules
        2. NLCD majority class → development category
        3. Default → ``"urban"``

    Args:
        assessor_use_code: Parcel's assessor/land use code if available.
        nlcd_majority: NLCD-derived majority class name.

    Returns:
        Development category string.
    """
    if assessor_use_code:
        code = assessor_use_code.strip().upper()
        # Check commercial/industrial first to avoid "R" false matches
        if any(x in code for x in ("COM", "RET", "OFF", "IND", "MFG", "WARE", "INDUST")):
            return "industrial"
        if any(x in code for x in ("AG", "FARM", "RANCH", "AGR")):
            return "agricultural"
        if any(x in code for x in ("PUB", "GOV", "GOVT", "SCH")):
            return "urban"
        if any(x in code for x in ("VAC", "VACANT")):
            return "natural"
        # Residential: be specific to avoid false matches
        if any(x in code for x in ("RES", "SFR", "MFR", "CONDO", "MULTI", "TOWNH")):
            return "urban"
        if len(code) > 1 and code[0] == "R" and code[1].isdigit():
            return "urban"
        if code == "R":
            return "urban"
        # Single-letter broad categories (after specific checks)
        if code in ("C", "I"):
            return "industrial"
        if code == "A":
            return "agricultural"
        if code == "P":
            return "urban"
        if code == "V":
            return "natural"

    if nlcd_majority:
        return nlcd_majority

    return "urban"
