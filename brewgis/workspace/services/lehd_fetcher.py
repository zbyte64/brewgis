"""LEHD → LODES employment data fetcher with CBP-based sub-sector splitting.

Downloads LODES (Longitudinal Employer-Household Dynamics) Workplace Area
Characteristics (WAC) data from the CES FTP server, and County Business
Patterns (CBP) data from the Census API for detailed sub-sector proportional
splitting.

Data available: 2002-2021.
See https://lehd.ces.census.gov/data/lodes/LODES7/ for documentation.
"""

from __future__ import annotations

import gzip
import io
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

logger = logging.getLogger(__name__)

# ── LODES WAC (Workplace Area Characteristics) ─────────────────────────

LODES_WAC_BASE = "https://lehd.ces.census.gov/data/lodes/LODES8"
# FIPS → state abbreviation mapping for LODES URL
_FIPS_TO_STATE: dict[str, str] = {
    "01": "al", "02": "ak", "04": "az", "05": "ar", "06": "ca",
    "08": "co", "09": "ct", "10": "de", "11": "dc", "12": "fl",
    "13": "ga", "15": "hi", "16": "id", "17": "il", "18": "in",
    "19": "ia", "20": "ks", "21": "ky", "22": "la", "23": "me",
    "24": "md", "25": "ma", "26": "mi", "27": "mn", "28": "ms",
    "29": "mo", "30": "mt", "31": "ne", "32": "nv", "33": "nh",
    "34": "nj", "35": "nm", "36": "ny", "37": "nc", "38": "nd",
    "39": "oh", "40": "ok", "41": "or", "42": "pa", "44": "ri",
    "45": "sc", "46": "sd", "47": "tn", "48": "tx", "49": "ut",
    "50": "vt", "51": "va", "53": "wa", "54": "wv", "55": "wi",
    "56": "wy", "72": "pr",
}


# LODES WAC columns: w_geocode (15-digit GEOID), C000 (total jobs),
# CNS01-CNS17 (NAICS sector aggregates per block)

LODES_WAC_VARIABLES: dict[str, str] = {
    "C000": "emp",
    "CNS01": "cns_goods_producing",
    "CNS02": "cns_manufacturing",
    "CNS03": "cns_trade_transport_utilities",
    "CNS04": "cns_information",
    "CNS05": "cns_finance_insurance",
    "CNS06": "cns_real_estate",
    "CNS07": "cns_professional_services",
    "CNS08": "cns_management",
    "CNS09": "cns_admin_support",
    "CNS10": "cns_educational_services",
    "CNS11": "cns_health_care",
    "CNS12": "cns_arts_entertainment",
    "CNS13": "cns_accommodation_food",
    "CNS14": "cns_other_services",
    "CNS15": "cns_public_administration",
    "CNS16": "cns_unclassified",
    "CNS17": "cns_armed_forces",
}

# ── CBP-Based Sub-Sector Splitting Rules ──────────────────────────────
#
# Each key is a LODES CNS column name. The value is a list of (target_sub_sector, source_spec)
# tuples where source_spec is:
#   * A string (NAICS regex pattern) — proportion is derived from CBP employment
#   * A float — fixed fraction of the CNS total
#   * None — takes the remainder after all previous non-None entries in the list
#
# CBP proportions are computed per-county from Census CBP API data.

_NAICS_SPLIT_RULES: dict[str, list[tuple[str, str | float | None]]] = {
    # CNS01 (Goods producing NAICS 11-23) → CBP-based split
    "CNS01": [
        ("emp_agriculture", r"^11\s*-*"),
        ("emp_extraction", r"^21\s*-*"),
        ("emp_construction", None),  # remainder (NAICS 23)
    ],
    # CNS02 (Manufacturing 31-33) → fixed national ratio
    "CNS02": [
        ("emp_manufacturing", 1.0),
    ],
    # CNS03 (Trade, Transport, Utilities) → CBP split
    "CNS03": [
        ("emp_transport_warehousing", r"^(48|49)\s*-*"),
        ("emp_utilities", r"^22\s*-*"),
        ("emp_wholesale", r"^42\s*-*"),              # split wholesale via CBP
        ("emp_retail_services", None),                # remainder = retail (44-45) only
    ],
    # CNS04-09 → all map to office services
    "CNS04": [("emp_office_services", 1.0)],  # Information (51)
    "CNS05": [("emp_office_services", 1.0)],  # Finance & Insurance (52)
    "CNS06": [("emp_office_services", 1.0)],  # Real Estate (53)
    "CNS07": [("emp_office_services", 1.0)],  # Professional Services (54)
    "CNS08": [("emp_office_services", 1.0)],  # Management (55)
    "CNS09": [("emp_office_services", 1.0)],  # Admin & Support (56)
    # CNS10-12 → direct mappings
    "CNS10": [("emp_education", 1.0)],              # Educational Services (61)
    "CNS11": [("emp_medical_services", 1.0)],         # Health Care (62)
    "CNS12": [("emp_arts_entertainment", 1.0)],       # Arts, Entertainment (71)
    # CNS13 (Accommodation/Food 72) → CBP split
    "CNS13": [
        ("emp_accommodation", r"^721\s*-*"),
        ("emp_restaurant", None),  # remainder (722)
    ],
    "CNS14": [("emp_other_services", 1.0)],   # Other Services (81)
    "CNS15": [("emp_public_admin", 1.0)],     # Public Administration (92)
    "CNS17": [("emp_military", 1.0)],          # Armed Forces
}

# Aggregate employment columns used in base canvas
AGGREGATE_MAPPINGS: dict[str, list[str]] = {
    "emp": [
        "emp_retail_services",
        "emp_restaurant",
        "emp_accommodation",
        "emp_arts_entertainment",
        "emp_other_services",
        "emp_office_services",
        "emp_medical_services",
        "emp_public_admin",
        "emp_education",
        "emp_manufacturing",
        "emp_wholesale",
        "emp_transport_warehousing",
        "emp_utilities",
        "emp_construction",
        "emp_agriculture",
        "emp_extraction",
        "emp_military",
    ],
    "emp_ret": [
        "emp_retail_services",
    ],
    "emp_off": [
        "emp_office_services",
    ],
    "emp_pub": [
        "emp_education",
        "emp_medical_services",
        "emp_public_admin",
    ],
    "emp_ind": [
        "emp_manufacturing",
        "emp_wholesale",
        "emp_transport_warehousing",
        "emp_utilities",
        "emp_construction",
        "emp_extraction",
        "emp_agriculture",
    ],
    "emp_ag": [
        "emp_agriculture",
    ],
    "emp_military": [
        "emp_military",
    ],
}


def _all_lodes_wac_vars() -> list[str]:
    """Return all LODES WAC variable codes (C000 + CNS codes)."""
    return list(LODES_WAC_VARIABLES.keys())


# ── LODES CSV Download ────────────────────────────────────────────────


def _build_lodes_wac_url(state_fips: str, county_fips: str, year: int = 2021) -> str:
    """Build the LODES WAC CSV URL for one state-county.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).

    Returns:
        URL to the gzipped CSV file.
    """
    state_fips_clean = state_fips.zfill(2)
    state_abbr = _FIPS_TO_STATE.get(state_fips_clean, "zz")
    return (
        f"{LODES_WAC_BASE}/{state_abbr}/wac/"
        f"{state_abbr}_wac_S000_JT00_{year}.csv.gz"
    )


def _fetch_lodes_csv(url: str) -> pd.DataFrame:
    """Download a LODES gzipped CSV and return as a DataFrame.

    Args:
        url: Fully qualified URL to a .csv.gz file.

    Returns:
        DataFrame with LODES columns.

    Raises:
        RuntimeError: On download or parse errors.
    """
    response = requests.get(url, timeout=120)
    if response.status_code != 200:  # noqa: PLR2004
        msg = f"LODES download returned HTTP {response.status_code}: {response.text[:500]}"
        raise RuntimeError(msg)

    try:
        decompressed = gzip.decompress(response.content)
    except Exception as e:
        msg = f"Failed to decompress gzipped LODES CSV: {e}"
        raise RuntimeError(msg) from e

    try:
        df = pd.read_csv(io.BytesIO(decompressed), dtype={"w_geocode": str})
    except Exception as e:
        msg = f"Failed to parse LODES CSV: {e}"
        raise RuntimeError(msg) from e

    return df


# ── CBP Proportion Computation ────────────────────────────────────────



def _parse_cbp_naics_emp(
    rows: list[list[str]],
    header: list[str],
) -> dict[str, float]:
    """Parse CBP API rows into a dict of NAICS code to employment count."""
    naics_emp: dict[str, float] = {}
    for row in rows:
        raw = dict(zip(header, row, strict=False))
        naics_raw = raw.get("NAICS2017", "").strip()
        emp_raw = raw.get("EMP", "").strip()
        if not naics_raw or not emp_raw or emp_raw in ("", "D", "S", "N"):
            continue
        try:
            emp_val = float(emp_raw)
        except (ValueError, TypeError):
            continue
        naics_clean = naics_raw.replace("-", "").replace(" ", "")
        if naics_clean in {"", "----"}:
            continue
        naics_emp[naics_clean] = emp_val
    return naics_emp


def _group_naics_by_prefix(
    naics_emp: dict[str, float],
    width: int = 2,
) -> dict[str, float]:
    """Group NAICS employment counts by prefix of ``width`` characters."""
    grouped: dict[str, float] = {}
    for code, val in naics_emp.items():
        prefix = code[:width]
        grouped[prefix] = grouped.get(prefix, 0) + val
    return grouped


def _cbp_proportion_in(
    naics_prefix: str,
    parent_prefixes: list[str],
    sector_emp: dict[str, float],
) -> float:
    """Return proportion of ``naics_prefix`` within ``parent_prefixes``."""
    total = sum(sector_emp.get(p, 0) for p in parent_prefixes)
    if total == 0:
        return 0.0
    return sector_emp.get(naics_prefix, 0) / total


def _build_cbp_proportions(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, float]:
    """Fetch CBP employment by NAICS code and compute within-sector proportions.

    Downloads County Business Patterns data for the given county, groups NAICS
    employment at the 2-6 digit level, and returns proportion of employment
    within each NAICS-parent group that each sub-sector accounts for.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).

    Returns:
        Dict mapping NAICS code prefix to proportion of employment within
        that NAICS sector. For example: "11" -> 0.15 (agriculture's share
        of goods-producing sectors).
    """
    state_fips_clean = state_fips.zfill(2)
    county_fips_clean = county_fips.zfill(3)

    url = (
        f"https://api.census.gov/data/{year}/cbp"
        f"?get=EMP,NAICS2017&for=county:{county_fips_clean}"
        f"&in=state:{state_fips_clean}"
    )

    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        raw_data: list[list[str]] = response.json()
    except requests.RequestException as exc:
        logger.warning("CBP API request failed: %s", exc)
        return {}
    except (ValueError, TypeError) as exc:
        logger.warning("CBP API returned non-JSON: %s", exc)
        return {}

    if len(raw_data) < 2:  # noqa: PLR2004
        logger.warning("CBP API returned no data rows.")
        return {}

    header = raw_data[0]
    rows = raw_data[1:]
    naics_emp = _parse_cbp_naics_emp(rows, header)

    sector_emp = _group_naics_by_prefix(naics_emp, 2)
    naics3_emp = _group_naics_by_prefix(naics_emp, 3)

    proportions: dict[str, float] = {}

    # CNS01 parent: NAICS 11, 21, 23
    goods_prefixes = ["11", "21", "23"]
    for pfx in goods_prefixes:
        proportions[pfx] = _cbp_proportion_in(pfx, goods_prefixes, sector_emp)

    # CNS03 parent: NAICS 22, 42, 44, 45, 48, 49
    ttu_prefixes = ["22", "42", "44", "45", "48", "49"]
    for pfx in ttu_prefixes:
        proportions[pfx] = _cbp_proportion_in(pfx, ttu_prefixes, sector_emp)

    # CNS13 parent: NAICS 721, 722 (3-digit accommodation/food)
    acc_food_total = naics3_emp.get("721", 0) + naics3_emp.get("722", 0)
    if acc_food_total > 0:
        proportions["721"] = naics3_emp.get("721", 0) / acc_food_total
        proportions["722"] = naics3_emp.get("722", 0) / acc_food_total
    else:
        proportions["721"] = 0.4
        proportions["722"] = 0.6

    return proportions


# ── Sub-Sector Column Splitting ───────────────────────────────────────



def _resolve_split_source(
    source_spec: str | float | None,
    total: float,
    cbp_proportions: dict[str, float],
) -> float:
    """Resolve a split rule source spec to a value."""
    if isinstance(source_spec, float):
        return total * source_spec
    if isinstance(source_spec, str):
        proportion = 0.0
        for naics_key, naics_prop in cbp_proportions.items():
            if re.match(source_spec, naics_key):
                proportion += naics_prop
        return total * proportion
    return 0.0


def _apply_naics_splits(
    row_cns: dict[str, int | float],
    cbp_proportions: dict[str, float],
) -> dict[str, float]:
    """Apply NAICS splitting rules to produce sub-sector column values.

    Args:
        row_cns: Dict mapping CNS column to job count for one block.
        cbp_proportions: Dict from ``_build_cbp_proportions``.

    Returns:
        Dict mapping sub-sector column name to computed value.
    """
    result: dict[str, float] = {}

    for cns_col, rules in _NAICS_SPLIT_RULES.items():
        total = float(row_cns.get(cns_col, 0))
        if total == 0:
            for target_col, _ in rules:
                result.setdefault(target_col, 0.0)
            continue

        fixed_totals: float = 0.0
        remainder_rule_idx: int | None = None

        for i, (target_col, source_spec) in enumerate(rules):
            if source_spec is None:
                remainder_rule_idx = i
            else:
                val = _resolve_split_source(source_spec, total, cbp_proportions)
                result[target_col] = result.get(target_col, 0.0) + val
                fixed_totals += val

        # Apply remainder if applicable
        if remainder_rule_idx is not None:
            target_col = rules[remainder_rule_idx][0]
            remainder = max(0.0, total - fixed_totals)
            result[target_col] = result.get(target_col, 0.0) + remainder

    return result


# ── Aggregate Column Computation ──────────────────────────────────────


def _compute_aggregate_employment(
    row: dict[str, float],
) -> dict[str, float]:
    """Compute aggregate employment columns from sub-sector columns.

    Args:
        row: Dict mapping sub-sector column name → value.

    Returns:
        Dict mapping aggregate column name → computed value.
    """
    result: dict[str, float] = {}
    for agg_col, detail_cols in AGGREGATE_MAPPINGS.items():
        total = sum(row.get(col, 0) for col in detail_cols)
        result[agg_col] = total
    return result


# ── Main Data Fetching Functions ──────────────────────────────────────


def fetch_lehd_block_data(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> gpd.GeoDataFrame:
    """Fetch LODES WAC employment data at the Census block level.

    Downloads the LODES WAC CSV and returns a GeoDataFrame with point
    geometry (placeholder centroids). For real polygon geometry, use
    ``fetch_lehd_block_polygons``.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).

    Returns:
        GeoDataFrame with columns: geoid, emp, aggregate columns,
        sub-sector columns, geometry (point centroid, EPSG:4326).

    Raises:
        RuntimeError: On download errors or empty data.
    """
    url = _build_lodes_wac_url(state_fips, county_fips, year)
    df = _fetch_lodes_csv(url)

    if df.empty:
        msg = "LODES WAC CSV returned no data."
        raise RuntimeError(msg)

    # Rename w_geocode → geoid
    df = df.rename(columns={"w_geocode": "geoid"})

    # Fetch CBP proportions once
    cbp_props = _build_cbp_proportions(state_fips, county_fips, year)

    records: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        geoid = str(row.get("geoid", ""))
        total_jobs = int(row.get("C000", 0)) if pd.notna(row.get("C000")) else 0

        # Build CNS column values
        cns_row: dict[str, int | float] = {}
        for cns_col in _NAICS_SPLIT_RULES:
            val = int(row.get(cns_col, 0)) if pd.notna(row.get(cns_col)) else 0
            cns_row[cns_col] = val

        # Apply sub-sector splitting
        subsectors = _apply_naics_splits(cns_row, cbp_props)

        # Compute aggregates
        aggregates = _compute_aggregate_employment(subsectors)

        record: dict[str, Any] = {
            "geoid": geoid,
        }
        record.update(subsectors)
        record.update(aggregates)
        record["emp"] = total_jobs

        records.append(record)

    if not records:
        msg = "No LODES records parsed."
        raise RuntimeError(msg)

    gdf = gpd.GeoDataFrame(records, geometry=_generate_block_points(records))
    gdf.crs = "EPSG:4326"

    return gdf


def _generate_block_points(records: list[dict]) -> list[Point]:
    """Generate placeholder point geometry for Census blocks.

    The LODES CSV doesn't include geometry. For real block geometry, use
    ``fetch_lehd_block_polygons`` which joins with TIGER/Line.

    Args:
        records: List of record dicts.

    Returns:
        List of Point geometries (EPSG:4326).
    """
    points: list[Point] = []
    for rec in records:
        h = hash(rec.get("geoid", ""))
        lng = -120.0 + (h % 1000) / 1000.0
        lat = 35.0 + ((h // 1000) % 1000) / 1000.0
        points.append(Point(lng, lat))
    return points


def fetch_lehd_data_summary(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, Any]:
    """Return a summary of available employment data for the given geography.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).

    Returns:
        Dict with keys: variables (list), row_count, aggregate_columns,
        sub_sector_columns.
    """
    try:
        url = _build_lodes_wac_url(state_fips, county_fips, year)
        df = _fetch_lodes_csv(url)
        row_count = len(df)

        # Collect all sub-sector columns from split rules
        sub_sector_cols = sorted(
            {col for rules in _NAICS_SPLIT_RULES.values() for col, _ in rules}
        )

        return {
            "variables": list(LODES_WAC_VARIABLES.values()),
            "sub_sector_columns": sub_sector_cols,
            "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
            "row_count": row_count,
        }
    except RuntimeError as e:
        return {
            "error": str(e),
            "variables": [],
            "sub_sector_columns": [],
            "aggregate_columns": [],
            "row_count": 0,
        }


# ── TIGER/Line polygon geometry ───────────────────────────────────────

_TIGER_CACHE_DIR = Path.home() / ".cache" / "brewgis" / "tiger_lehd"
_TIGER_YEAR = 2023


def _tiger_block_url(state_fips: str, _county_fips: str) -> str:
    """Build the TIGER/Line tabblock shapefile URL for one county.

    Uses TIGER2020 TABBLOCK (2010 Census vintage) to match LEHD LODES geographies.
    """
    return (
        f"https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK/"
        f"tl_2020_{state_fips}_tabblock10.zip"
    )


def _download_tiger_shapefile(url: str) -> bytes | None:
    """Download a TIGER/Line shapefile ZIP, returning raw bytes."""
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to download TIGER block shapefile: %s", exc)
        return None
    return response.content


def _read_tiger_block_polygons(zip_bytes: bytes) -> gpd.GeoDataFrame:
    """Read block polygon geometry from TIGER/Line ZIP bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "tiger_block.zip"
        zip_path.write_bytes(zip_bytes)
        gdf = gpd.read_file(f"zip://{zip_path}")
    if gdf.crs is None:
        gdf.set_crs("EPSG:4269", inplace=True)
    gdf = gdf.to_crs("EPSG:4326")
    # Handle TIGER column naming: 2020-vintage uses STATEFP10/COUNTYFP10/...
    # (TABBLOCK20) vs 2019-vintage uses STATEFP/COUNTYFP/... (TABBLOCK).
    sf_col = "STATEFP10" if "STATEFP10" in gdf.columns else "STATEFP"
    cf_col = "COUNTYFP10" if "COUNTYFP10" in gdf.columns else "COUNTYFP"
    tc_col = "TRACTCE10" if "TRACTCE10" in gdf.columns else "TRACTCE"
    bc_col = "BLOCKCE10" if "BLOCKCE10" in gdf.columns else "BLOCKCE"
    gdf["geoid"] = (
        gdf[sf_col].str.zfill(2)
        + gdf[cf_col].str.zfill(3)
        + gdf[tc_col].str.zfill(6)
        + gdf[bc_col].str.zfill(4)
    )
    return gdf[["geoid", "geometry"]]


def fetch_lehd_block_polygons(
    state_fips: str,
    county_fips: str,
    use_cache: bool = True,  # noqa: FBT001, FBT002
) -> gpd.GeoDataFrame:
    """Fetch LODES employment data with real block polygon geometry.

    Downloads LODES WAC CSV for employment attributes and TIGER/Line
    tabblock shapefiles for polygon geometry, then joins on GEOID.

    Falls back to point-based geometry (from ``fetch_lehd_block_data``) if
    TIGER shapefiles are unavailable.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        use_cache: Cache TIGER shapefiles on disk (default True).

    Returns:
        GeoDataFrame with polygon geometry, ``geoid``, and all
        employment columns mapped to BaseCanvasSchema names.
    """
    # 1. Fetch LODES attribute data
    lehd_gdf = fetch_lehd_block_data(state_fips, county_fips)
    # Filter state-level LODES data to this county (GEOID prefix = state_fips + county_fips)
    county_geoid_prefix = state_fips.zfill(2) + county_fips.zfill(3)
    pre_count = len(lehd_gdf)
    lehd_gdf = lehd_gdf[lehd_gdf["geoid"].str.startswith(county_geoid_prefix)].copy()
    logger.info(
        "Filtered LODES from %d to %d blocks for county %s",
        pre_count, len(lehd_gdf), county_fips,
    )
    if lehd_gdf.empty:
        logger.warning("No LODES blocks match county FIPS %s", county_fips)
        return lehd_gdf


    # 2. Try to get TIGER polygon geometry
    url = _tiger_block_url(state_fips, county_fips)
    tiger_gdf: gpd.GeoDataFrame | None = None

    if use_cache:
        cache_dir = _TIGER_CACHE_DIR / state_fips / county_fips
        cache_path = cache_dir / "block.geojson"
        if cache_path.exists():
            logger.info("Loading cached TIGER blocks from %s", cache_path)
            tiger_gdf = gpd.read_file(str(cache_path))
        else:
            raw = _download_tiger_shapefile(url)
            if raw is not None:
                try:
                    tiger_gdf = _read_tiger_block_polygons(raw)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    tiger_gdf.to_file(str(cache_path), driver="GeoJSON")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to parse TIGER blocks: %s", exc)
                    tiger_gdf = None
    else:
        raw = _download_tiger_shapefile(url)
        if raw is not None:
            try:
                tiger_gdf = _read_tiger_block_polygons(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse TIGER blocks: %s", exc)
                tiger_gdf = None

    if tiger_gdf is not None and not tiger_gdf.empty:
        # 3. Join LODES attributes to polygon geometry on GEOID
        lehd_attrs = lehd_gdf.drop(columns=["geometry"], errors="ignore")
        joined = tiger_gdf.merge(lehd_attrs, on="geoid", how="inner")
        if joined.empty:
            logger.warning(
                "LODES data did not match TIGER blocks for %s/%s; "
                "falling back to point geometry",
                state_fips,
                county_fips,
            )
            result = lehd_gdf.copy()
        else:
            result = joined
    else:
        logger.warning(
            "TIGER blocks unavailable for %s/%s; using point-based geometry",
            state_fips,
            county_fips,
        )
        result = lehd_gdf.copy()

    return result
