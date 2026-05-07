"""LEHD (Longitudinal Employer-Household Dynamics) employment data fetcher.

Queries the Census LED (Longitudinal Employer Dynamics) API for Workplace Area
Characteristics (WAC) data at the Census block level.

Data available: 2002–2021 (lagging indicator).
See https://lehd.ces.census.gov/data/ for documentation.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import Point

logger = logging.getLogger(__name__)

# LEHD WAC API base — RAC (Residence Area Characteristics) and WAC (Workplace)
LEHD_BASE = "https://api.census.gov/data/2021/lehd"

# WAC variable groups mapped to base canvas employment columns
# S000 = Total jobs
# SA01 = Age 29 or younger
# SA02 = Age 30 to 54
# SA03 = Age 55 or older
# SE01 = Earnings $1250/month or less
# SE02 = Earnings $1251/month to $3333/month
# SE03 = Earnings $3334/month or more
# SI01 = Goods producing
# SI02 = Trade, transportation, utilities
# SI03 = All other services
WAC_VARIABLES = {
    "C000": "emp",  # Total jobs
    "CA01": "emp_ag",  # Agriculture, forestry, fishing, hunting
    "CA02": "emp_mining",  # Mining, quarrying, oil/gas
    "CA03": "emp_util",  # Utilities
    "CA04": "emp_constr",  # Construction
    "CA05": "emp_mfg",  # Manufacturing
    "CA06": "emp_wholesale",  # Wholesale trade
    "CA07": "emp_retail",  # Retail trade
    "CA08": "emp_trans",  # Transportation/warehousing
    "CA09": "emp_info",  # Information
    "CA10": "emp_finance",  # Finance/insurance
    "CA11": "emp_realestate",  # Real estate
    "CA12": "emp_professional",  # Professional/scientific/technical services
    "CA13": "emp_management",  # Management of companies
    "CA14": "emp_admin",  # Administrative/support/waste mgmt
    "CA15": "emp_edu",  # Educational services
    "CA16": "emp_healthcare",  # Healthcare/social assistance
    "CA17": "emp_arts",  # Arts/entertainment/recreation
    "CA18": "emp_accomodation",  # Accommodation/food services
    "CA19": "emp_other",  # Other services
    "CA20": "emp_pub_admin",  # Public administration
}

# Aggregate employment columns used in base canvas
AGGREGATE_MAPPINGS: dict[str, list[str]] = {
    "emp_ret": [
        "emp_retail",
    ],
    "emp_off": [
        "emp_professional",
        "emp_finance",
        "emp_realestate",
        "emp_management",
        "emp_admin",
        "emp_info",
    ],
    "emp_pub": [
        "emp_edu",
        "emp_healthcare",
        "emp_pub_admin",
    ],
    "emp_ind": [
        "emp_mfg",
        "emp_mining",
        "emp_util",
        "emp_constr",
        "emp_trans",
        "emp_wholesale",
    ],
    "emp_ag": [
        "emp_ag",
    ],
    "emp_military": [],  # Not directly available from LEHD WAC
}


def _all_wac_vars() -> list[str]:
    """Return all LEHD WAC variable codes."""
    return list(WAC_VARIABLES.keys())


def _build_wac_url(state_fips: str, county_fips: str) -> str:
    """Build the LEHD WAC API URL.

    LEHD WAC data is at the Census block level. We query blocks within the
    given county.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        URL string to query.
    """
    vars_ = ",".join(_all_wac_vars())
    return f"{LEHD_BASE}/wac?get={vars_}&state:{state_fips}&in=county:{county_fips}&for=block:*"


def _fetch_lehd_data(url: str) -> list[list[str]]:
    """Fetch data from the LEHD API and return raw rows.

    Args:
        url: Fully qualified LEHD API URL.

    Returns:
        List of rows, where each row is a list of string values.

    Raises:
        RuntimeError: On HTTP or parse errors.
    """
    response = requests.get(url, timeout=60)
    if response.status_code != 200:
        msg = f"LEHD API returned HTTP {response.status_code}: {response.text}"
        raise RuntimeError(msg)

    try:
        data: list[list[str]] = response.json()
    except ValueError as e:
        msg = f"LEHD API returned non-JSON response: {e}"
        raise RuntimeError(msg) from e

    return data


def _compute_aggregate_employment(
    row: dict[str, int],
) -> dict[str, int | float]:
    """Compute aggregate employment columns from detailed NAICS categories.

    Args:
        row: Dict mapping LEHD variable → integer count.

    Returns:
        Dict mapping aggregate column name → computed value.
    """
    result: dict[str, int | float] = {}
    for agg_col, detail_cols in AGGREGATE_MAPPINGS.items():
        total = sum(row.get(col, 0) for col in detail_cols)
        result[agg_col] = total
    return result


def fetch_lehd_block_data(
    state_fips: str,
    county_fips: str,
) -> gpd.GeoDataFrame:
    """Fetch LEHD WAC employment data at the Census block level.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        GeoDataFrame with columns: state, county, tract, block,
        emp, emp_ret, emp_off, emp_pub, emp_ind, emp_ag, emp_military,
        and detailed industry columns, geometry (point centroid).

    Raises:
        RuntimeError: On API errors or empty data.
    """
    url = _build_wac_url(state_fips, county_fips)
    data = _fetch_lehd_data(url)

    if len(data) < 2:
        msg = "LEHD API returned no data rows."
        raise RuntimeError(msg)

    header = data[0]
    rows = data[1:]

    records: list[dict[str, Any]] = []
    for r in rows:
        raw = dict(zip(header, r, strict=False))

        int_row: dict[str, int] = {}
        for var in _all_wac_vars():
            try:
                int_row[var] = int(raw.get(var, 0)) if raw.get(var) else 0
            except (ValueError, TypeError):
                int_row[var] = 0

        record: dict[str, Any] = {
            "state": raw.get("state", ""),
            "county": raw.get("county", ""),
            "tract": raw.get("tract", ""),
            "block": raw.get("block", ""),
            "geoid": f"{raw.get('state', '')}{raw.get('county', '')}{raw.get('tract', '')}{raw.get('block', '')}",
        }

        # Map WAC variables to columns
        for var, col in WAC_VARIABLES.items():
            record[col] = int_row.get(var, 0)

        # Compute aggregates
        aggregates = _compute_aggregate_employment(int_row)
        record.update(aggregates)

        # Default military (not available from LEHD WAC)
        record["emp_military"] = 0

        records.append(record)

    if not records:
        msg = "No LEHD records parsed from API response."
        raise RuntimeError(msg)

    df = gpd.GeoDataFrame(records, geometry=_generate_block_points(records))
    df.crs = "EPSG:4326"

    # Drop raw variable columns that aren't canvas columns
    drop_cols = [c for c in df.columns if c.upper() in _all_wac_vars()]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    return df


def _generate_block_points(records: list[dict]) -> list[Point]:
    """Generate placeholder point geometry for Census blocks.

    The LEHD API doesn't return geometry. For real block geometry, users
    should import TIGER/Line block shapefiles.

    Args:
        records: List of record dicts.

    Returns:
        List of Point geometries (EPSG:4326).
    """
    points: list[Point] = []
    for rec in records:
        h = hash(rec.get("geoid", f"{rec.get('tract', '')}_{rec.get('block', '')}"))
        lng = -120.0 + (h % 1000) / 1000.0
        lat = 35.0 + ((h // 1000) % 1000) / 1000.0
        points.append(Point(lng, lat))
    return points


def fetch_lehd_data_summary(state_fips: str, county_fips: str) -> dict[str, Any]:
    """Return a summary of LEHD data available for the given geography.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        Dict with keys: variables (list), row_count, aggregate_columns.
    """
    try:
        url = _build_wac_url(state_fips, county_fips)
        data = _fetch_lehd_data(url)
        row_count = max(0, len(data) - 1)

        return {
            "variables": list(WAC_VARIABLES.values()),
            "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
            "row_count": row_count,
        }
    except RuntimeError as e:
        return {
            "error": str(e),
            "variables": [],
            "aggregate_columns": [],
            "row_count": 0,
        }
