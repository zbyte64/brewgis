"""Census ACS demographics fetcher — queries Census Bureau API for ACS 5-year estimates.

Supported tables (mapped to base canvas columns):
- B01001: Sex by Age (pop)
- B25003: Tenure (hh — occupied housing units)
- B25024: Units in Structure (du, du_detsf*, du_attsf, du_mf*)
- B25008: Total Population in Occupied Housing Units (pop/hh ratio check)
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import zlib
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Point

logger = logging.getLogger(__name__)


# Census API base
def _census_base_url(year: int = 2022) -> str:
    return f"https://api.census.gov/data/{year}/acs/acs5"


# ACS variable definitions mapped to base canvas columns
# Grouped so we can fetch them efficiently via a single call
ACS_TABLE_GROUPS = {
    "B01001": {
        "label": "Sex by Age",
        "vars": ["B01001_001E"],  # Total population
    },
    "B25003": {
        "label": "Tenure",
        "vars": ["B25003_001E", "B25003_002E", "B25003_003E"],
        # _001E = Total occupied, _002E = Owner occupied, _003E = Renter occupied
    },
    "B25024": {
        "label": "Units in Structure",
        "vars": [
            "B25024_001E",  # Total
            "B25024_002E",  # 1, detached
            "B25024_003E",  # 1, attached
            "B25024_004E",  # 2
            "B25024_005E",  # 3 or 4
            "B25024_006E",  # 5 to 9
            "B25024_007E",  # 10 to 19
            "B25024_008E",  # 20 to 49
            "B25024_009E",  # 50+
        ],
    },
    "B25008": {
        "label": "Total Population in Occupied Housing Units",
        "vars": ["B25008_001E", "B25008_002E", "B25008_003E"],
        # _001E = Total, _002E = Owner occupied, _003E = Renter occupied
    },
    "B19013": {
        "label": "Median Household Income",
        "vars": ["B19013_001E"],  # Median household income in the past 12 months
    },
    "B25070": {
        "label": "Gross Rent as Percentage of Household Income",
        "vars": [
            "B25070_001E",  # Total
            "B25070_007E",  # 30.0 to 34.9 percent
            "B25070_008E",  # 35.0 to 39.9 percent
            "B25070_009E",  # 40.0 to 49.9 percent
            "B25070_010E",  # 50.0 percent or more
        ],
    },
    "B25091": {
        "label": "Mortgage Status by Selected Monthly Owner Costs",
        "vars": [
            "B25091_001E",  # Total owner-occupied
            "B25091_005E",  # With mortgage: 30.0 to 34.9%
            "B25091_006E",  # With mortgage: 35.0 to 49.9%
            "B25091_007E",  # With mortgage: 50.0%+
            "B25091_011E",  # Not mortgaged: 30.0 to 34.9%
            "B25091_012E",  # Not mortgaged: 35.0 to 49.9%
            "B25091_013E",  # Not mortgaged: 50.0%+
        ],
    },
    "B03002": {
        "label": "Hispanic or Latino Origin by Race",
        "vars": [
            "B03002_001E",  # Total
            "B03002_002E",  # Not Hispanic or Latino: White alone
            "B03002_003E",  # Not Hispanic or Latino: Black or African American alone
            "B03002_004E",  # Not Hispanic or Latino: American Indian and Alaska Native alone
            "B03002_005E",  # Not Hispanic or Latino: Asian alone
            "B03002_012E",  # Hispanic or Latino
        ],
    },
    "B15003": {
        "label": "Educational Attainment",
        "vars": [
            "B15003_001E",  # Total
            "B15003_022E",  # Bachelor's degree
            "B15003_023E",  # Master's degree
            "B15003_024E",  # Professional school degree
            "B15003_025E",  # Doctorate degree
        ],
    },
}


def _all_vars() -> list[str]:
    """Return all ACS variable codes across all table groups."""
    result: list[str] = []
    for group in ACS_TABLE_GROUPS.values():
        result.extend(group["vars"])
    return result


def _build_census_url(
    state_fips: str, county_fips: str, summary_level: str, year: int = 2022
) -> str:
    """Build the Census API URL for the given geography.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        summary_level: 'block group' or 'tract'.

    Returns:
        URL string to query.
    """
    vars_ = ",".join(_all_vars())
    if summary_level == "block group":
        geo = f"in=state:{state_fips}&in=county:{county_fips}&for=block%20group:*"
    elif summary_level == "tract":
        geo = f"in=state:{state_fips}&in=county:{county_fips}&for=tract:*"
    else:
        geo = f"in=state:{state_fips}&in=county:{county_fips}&for=block%20group:*"

    return f"{_census_base_url(year)}?get={vars_}&{geo}"


def _fetch_census_data(url: str) -> list[list[str]]:
    """Fetch data from the Census API and return raw rows.

    Args:
        url: Fully qualified Census API URL.

    Returns:
        List of rows, where each row is a list of string values.
        First row is the header.

    Raises:
        RuntimeError: On HTTP or parse errors.
    """
    response = requests.get(url, timeout=60)
    if response.status_code != 200:
        msg = f"Census API returned HTTP {response.status_code}: {response.text}"
        raise RuntimeError(msg)

    try:
        data: list[list[str]] = response.json()
    except ValueError as e:
        msg = f"Census API returned non-JSON response: {e}"
        raise RuntimeError(msg) from e

    return data


def _safe_pct(numerator: int, denominator: int) -> float:
    """Compute percentage safely, returning 0.0 for zero denominator."""
    if denominator > 0:
        return round(numerator / denominator * 100.0, 2)
    return 0.0


def _compute_derived_columns(row: dict[str, int]) -> dict[str, int | float]:
    """Compute derived base canvas columns from raw ACS variables.

    Args:
        row: Dict mapping ACS variable → integer count.

    Returns:
        Dict mapping canvas column → computed value.
    """
    pop = row.get("B01001_001E", 0)
    hh = row.get("B25003_001E", 0)
    du = row.get("B25024_001E", 0)

    # Single-family detached
    du_detsf = row.get("B25024_002E", 0)
    # Single-family attached
    du_attsf = row.get("B25024_003E", 0)
    # Multi-family (2-9 units)
    du_mf_2_9 = (
        row.get("B25024_004E", 0)
        + row.get("B25024_005E", 0)
        + row.get("B25024_006E", 0)
    )
    # Multi-family (10+ units)
    du_mf_10p = (
        row.get("B25024_007E", 0)
        + row.get("B25024_008E", 0)
        + row.get("B25024_009E", 0)
    )

    # Combined cost burden (owners + renters)
    owner_cost_burdened = (
        row.get("B25091_005E", 0)
        + row.get("B25091_006E", 0)
        + row.get("B25091_007E", 0)
        + row.get("B25091_011E", 0)
        + row.get("B25091_012E", 0)
        + row.get("B25091_013E", 0)
    )
    renter_cost_burdened = (
        row.get("B25070_007E", 0)
        + row.get("B25070_008E", 0)
        + row.get("B25070_009E", 0)
        + row.get("B25070_010E", 0)
    )
    total_cost_burdened = owner_cost_burdened + renter_cost_burdened
    total_households = row.get("B25003_001E", 0)

    return {
        "pop": pop,
        "hh": hh,
        "du": du,
        "du_detsf": du_detsf,
        "du_attsf": du_attsf,
        "du_mf_2_9": du_mf_2_9,
        "du_mf_10p": du_mf_10p,
        "owner_occupied": row.get("B25003_002E", 0),
        "renter_occupied": row.get("B25003_003E", 0),
        "median_income": row.get("B19013_001E", 0),
        "rent_burden_pct": _safe_pct(renter_cost_burdened, row.get("B25070_001E", 0)),
        "cost_burden_pct": _safe_pct(total_cost_burdened, total_households),
        "total_population": row.get("B03002_001E", 0),
        "pct_minority": _safe_pct(
            row.get("B03002_001E", 0) - row.get("B03002_002E", 0),
            row.get("B03002_001E", 0),
        ),
        "pct_college_educated": _safe_pct(
            row.get("B15003_022E", 0)
            + row.get("B15003_023E", 0)
            + row.get("B15003_024E", 0)
            + row.get("B15003_025E", 0),
            row.get("B15003_001E", 0),
        ),
    }


def fetch_acs_block_groups(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
) -> gpd.GeoDataFrame:
    """Fetch ACS 5-year demographics at the block group level for one county.

    Note: The Census API's basic query endpoint returns tabular data without
    geometry. This function returns a GeoDataFrame with point geometry derived
    from the block group centroid (TRACT + BLOCK GROUP). For polygon geometry,
    use the cartographic boundary shapefiles from the Census FTP server.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).


    Returns:
        GeoDataFrame with columns: state, county, tract, block_group,
        pop, hh, du, du_detsf, du_attsf, du_mf_2_9, du_mf_10p,
        owner_occupied, renter_occupied, geometry.

    Raises:
        RuntimeError: On API errors or empty data.
    """
    url = _build_census_url(state_fips, county_fips, "block group", year)

    data = _fetch_census_data(url)

    if len(data) < 2:
        msg = "Census API returned no data rows."
        raise RuntimeError(msg)

    header = data[0]
    rows = data[1:]

    # Parse into dicts keyed by GEOID
    records: list[dict[str, Any]] = []
    for r in rows:
        raw = dict(zip(header, r, strict=False))

        record: dict[str, Any] = {
            "state": raw.get("state", ""),
            "county": raw.get("county", ""),
            "tract": raw.get("tract", ""),
            "block_group": raw.get("block group", ""),
        }

        # Parse integer values from ACS variables
        int_row: dict[str, int] = {}
        for var in _all_vars():
            try:
                int_row[var] = int(raw.get(var, 0)) if raw.get(var) else 0
            except (ValueError, TypeError):
                int_row[var] = 0

        # Compute derived columns
        derived = _compute_derived_columns(int_row)
        record.update(derived)

        # Build centroid geometry from TRACT + BLOCK GROUP
        # This is a point in tract space; not a real polygon
        geoid = f"{record['state']}{record['county']}{record['tract']}{record['block_group']}"
        record["geoid"] = geoid

        records.append(record)

    if not records:
        msg = "No census records parsed from API response."
        raise RuntimeError(msg)

    df = gpd.GeoDataFrame(records, geometry=_generate_block_group_points(records))
    df.crs = "EPSG:4326"
    return df


def _generate_block_group_points(records: list[dict]) -> list[Point]:
    """Generate placeholder point geometry for block groups.

    The Census basic API doesn't return geometry. For real polygon geometry,
    users should import TIGER/Line shapefiles. This creates centroid points
    using a grid offset based on tract+block group to avoid total overlap.

    Args:
        records: List of record dicts with state/county/tract/block_group.

    Returns:
        List of Point geometries (EPSG:4326).
    """
    points: list[Point] = []
    for rec in records:
        # Use tract and block_group as a crude spatial offset
        tract_str = f"{rec['tract']}.{rec['block_group']}"
        # Hash the geoid to produce a stable lat/lng within the county
        h = hash(rec.get("geoid", tract_str))
        lng = -120.0 + (h % 1000) / 1000.0
        lat = 35.0 + ((h // 1000) % 1000) / 1000.0
        points.append(Point(lng, lat))

    return points


def fetch_acs_data_summary(
    state_fips: str, county_fips: str, year: int = 2022
) -> dict[str, Any]:
    """Return a summary of ACS data available for the given geography.

    Useful for the UI to show what data is available before importing.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).


    Returns:
        Dict with keys: table_groups (list of table IDs), row_count,
        and sample columns.
    """
    try:
        url = _build_census_url(state_fips, county_fips, "block group", year)

        data = _fetch_census_data(url)
        row_count = max(0, len(data) - 1)

        return {
            "table_groups": list(ACS_TABLE_GROUPS.keys()),
            "row_count": row_count,
            "columns": [
                "pop",
                "hh",
                "du",
                "du_detsf",
                "du_attsf",
                "du_mf_2_9",
                "du_mf_10p",
                "owner_occupied",
                "renter_occupied",
                "median_income",
                "rent_burden_pct",
                "total_population",
                "pct_minority",
                "pct_college_educated",
            ],
        }
    except RuntimeError as e:
        return {"error": str(e), "table_groups": [], "row_count": 0, "columns": []}


# ── TIGER/Line polygon geometry ───────────────────────────────────────

_TIGER_CACHE_DIR = Path.home() / ".cache" / "brewgis" / "tiger"
_TIGER_YEAR = 2023
# National proportions for splitting ACS DU subtypes
_DU_MF_2_9_TO_MF2TO4_RATIO = 0.40  # 40% of 2-9 units → 2-4 units


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


# ── Single-Family Lot Size Split Ratio ────────────────────────────────
# Controls what fraction of detached single-family dwelling units (du_detsf)
# are classified as "small lot" (du_detsf_sl) vs "large lot" (du_detsf_ll).
#
# SACOG convention uses ~1/8 acre (~5,445 sqft) lot size as the threshold
# between small-lot and large-lot single-family. The national default of
# 0.40 (40% small lot) is a statistical approximation based on ACS
# units-in-structure distributions and national parcel data.
#
# To calibrate for a specific region, override this module-level variable
# before running the ETL, or set the BREWGIS_DETSF_SL_RATIO env var.
# For SACOG Sacramento County, the reference v1 dataset split is roughly
# 67% large-lot / 33% small-lot (ratio ~0.33), though this varies by
# jurisdiction within the county.
try:
    _raw = float(os.environ.get("BREWGIS_DETSF_SL_RATIO", "0.40"))
    _DU_DETSF_TO_SL_RATIO: float = max(0.0, _raw)
except (ValueError, TypeError):
    _DU_DETSF_TO_SL_RATIO: float = 0.40


def _tiger_bg_url(state_fips: str, county_fips: str) -> str:
    """Build the TIGER/Line block group shapefile URL for one county.

    Note: TIGER 2023+ BG files are state-level (one file per state).
    The county param is kept for compatibility but the download is
    per-state.
    """
    return (
        f"https://www2.census.gov/geo/tiger/TIGER{_TIGER_YEAR}/BG/"
        f"tl_{_TIGER_YEAR}_{state_fips}_bg.zip"
    )


def _download_tiger_shapefile(
    url: str,
    *,
    refresh_cache: bool = False,
    cache_dir: Path | None = None,
) -> bytes | None:
    """Download a TIGER/Line shapefile ZIP, returning raw bytes.

    Caches the raw ZIP bytes locally with companion .size and .crc32
    files for integrity verification. On verification failure the
    cached file is removed and re-downloaded.

    Args:
        url: TIGER/Line shapefile ZIP URL.
        refresh_cache: If True, delete cached files and re-download.
        cache_dir: Override cache directory (defaults to _TIGER_CACHE_DIR).

    Returns:
        Raw ZIP bytes, or None if download failed.
    """
    cache_dir = cache_dir or _TIGER_CACHE_DIR
    filename = url.rstrip("/").rsplit("/", 1)[-1]
    cache_path = cache_dir / filename
    size_path = cache_dir / f"{filename}.size"
    crc32_path = cache_dir / f"{filename}.crc32"

    if refresh_cache:
        for p in [cache_path, size_path, crc32_path]:
            p.unlink(missing_ok=True)

    if cache_path.exists() and _verify_cached_bytes(cache_path, size_path, crc32_path):
        logger.info("Loading cached TIGER shapefile from %s", cache_path)
        return cache_path.read_bytes()

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.content
    except requests.RequestException as exc:
        logger.warning("Failed to download TIGER shapefile: %s", exc)
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        size_path.write_text(content_length)
    crc32_path.write_text(str(zlib.crc32(data)))
    logger.info("Cached TIGER shapefile at %s", cache_path)
    return data


def _read_tiger_bg_polygons(zip_bytes: bytes) -> gpd.GeoDataFrame:
    """Read block-group polygon geometry from TIGER/Line ZIP bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tiger_bg.zip")
        with open(zip_path, "wb") as tmp:
            tmp.write(zip_bytes)
        gdf = gpd.read_file(f"zip://{zip_path}")
    if gdf.crs is None:
        gdf.set_crs("EPSG:4269", inplace=True)
    gdf = gdf.to_crs("EPSG:4326")
    # Build GEOID from TIGER fields
    gdf["geoid"] = (
        gdf["STATEFP"].str.zfill(2)
        + gdf["COUNTYFP"].str.zfill(3)
        + gdf["TRACTCE"].str.zfill(6)
        + gdf["BLKGRPCE"].str.zfill(1)
    )
    return gdf[["geoid", "geometry"]]


def _apply_acs_column_mapping(
    block_groups: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Map ACS-derived column names to BaseCanvasSchema equivalents.

    Resolves the differences between ACS DU subtypes and the schema:
        * du_mf_2_9 → split into du_mf2to4 and du_mf5p via _DU_MF_2_9_TO_MF2TO4_RATIO
        * du_mf_10p → added to du_mf5p
        * du_detsf → split into du_detsf_sl and du_detsf_ll via _DU_DETSF_TO_SL_RATIO
    """
    if "du_mf_2_9" in block_groups.columns:
        mf_2_9 = block_groups["du_mf_2_9"].fillna(0.0)
        block_groups["du_mf2to4"] = (mf_2_9 * _DU_MF_2_9_TO_MF2TO4_RATIO).round(1)
        block_groups["du_mf5p"] = (mf_2_9 * (1 - _DU_MF_2_9_TO_MF2TO4_RATIO)).round(1)
        if "du_mf_10p" in block_groups.columns:
            block_groups["du_mf5p"] += block_groups["du_mf_10p"].fillna(0.0)
        block_groups.drop(
            columns=["du_mf_2_9", "du_mf_10p"], inplace=True, errors="ignore"
        )
    else:
        block_groups["du_mf2to4"] = 0.0
        block_groups["du_mf5p"] = 0.0

    # Compute aggregate du_mf from sub-types
    block_groups["du_mf"] = block_groups["du_mf2to4"].fillna(0.0) + block_groups[
        "du_mf5p"
    ].fillna(0.0)
    if "du_detsf" in block_groups.columns:
        detsf = block_groups["du_detsf"].fillna(0.0)
        block_groups["du_detsf_sl"] = (detsf * _DU_DETSF_TO_SL_RATIO).round(1)
        block_groups["du_detsf_ll"] = (detsf * (1 - _DU_DETSF_TO_SL_RATIO)).round(1)
        block_groups.drop(columns=["du_detsf"], inplace=True, errors="ignore")
    else:
        block_groups["du_detsf_sl"] = 0.0
        block_groups["du_detsf_ll"] = 0.0

    return block_groups


def fetch_acs_block_group_polygons(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
    use_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Fetch ACS demographics with real polygon geometry.

    Downloads TIGER/Line block-group shapefiles from the Census FTP server,
    joins ACS attribute data from the Census API, and applies column
    mappings to match the BaseCanvasSchema.

    Falls back to point-in-parcel assignment (the existing point-based
    geometry from fetch_acs_block_groups) if TIGER shapefiles are
    unavailable.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).
        use_cache: Cache TIGER shapefiles on disk (default True).

    Returns:
        GeoDataFrame with polygon geometry, geoid, and all
        demographic columns mapped to BaseCanvasSchema names.
    """
    # 1. Fetch ACS attribute data
    acs_gdf = fetch_acs_block_groups(state_fips, county_fips, year)

    # 2. Try to get TIGER polygon geometry
    url = _tiger_bg_url(state_fips, county_fips)

    if use_cache:
        cache_dir = _TIGER_CACHE_DIR / state_fips / county_fips
        cache_path = cache_dir / "bg.geojson"
        if cache_path.exists():
            logger.info("Loading cached TIGER polygons from %s", cache_path)
            tiger_gdf = gpd.read_file(str(cache_path))
        else:
            raw = _download_tiger_shapefile(url)
            if raw is not None:
                tiger_gdf = _read_tiger_bg_polygons(raw)
                cache_dir.mkdir(parents=True, exist_ok=True)
                tiger_gdf.to_file(str(cache_path), driver="GeoJSON")
            else:
                tiger_gdf = None
    else:
        raw = _download_tiger_shapefile(url)
        tiger_gdf = _read_tiger_bg_polygons(raw) if raw is not None else None

    if tiger_gdf is not None and not tiger_gdf.empty:
        # 3. Join ACS attributes to polygon geometry on GEOID
        acs_attrs = acs_gdf.drop(columns=["geometry"], errors="ignore")
        joined = tiger_gdf.merge(acs_attrs, on="geoid", how="inner")
        if joined.empty:
            logger.warning(
                "ACS data did not match TIGER polygons for %s/%s; falling back to point geometry",
                state_fips,
                county_fips,
            )
            result = acs_gdf.copy()
        else:
            result = joined
    else:
        logger.warning(
            "TIGER polygons unavailable for %s/%s; using point-based geometry",
            state_fips,
            county_fips,
        )
        result = acs_gdf.copy()

    # 4. Apply column mapping
    return _apply_acs_column_mapping(result)
