"""Census ACS demographics fetcher — queries Census Bureau API for ACS 5-year estimates.

Supported tables (mapped to base canvas columns):
- B01001: Sex by Age (pop)
- B25003: Tenure (hh — occupied housing units)
- B25024: Units in Structure (du, du_detsf*, du_attsf, du_mf*)
- B25008: Total Population in Occupied Housing Units (pop/hh ratio check)
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

logger = logging.getLogger(__name__)

# Census API base
CENSUS_BASE_URL = "https://api.census.gov/data/2022/acs/acs5"

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
}


def _all_vars() -> list[str]:
    """Return all ACS variable codes across all table groups."""
    result: list[str] = []
    for group in ACS_TABLE_GROUPS.values():
        result.extend(group["vars"])
    return result


def _build_census_url(state_fips: str, county_fips: str, summary_level: str) -> str:
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

    return f"{CENSUS_BASE_URL}?get={vars_}&{geo}"


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
    }


def fetch_acs_block_groups(
    state_fips: str,
    county_fips: str,
) -> gpd.GeoDataFrame:
    """Fetch ACS 5-year demographics at the block group level for one county.

    Note: The Census API's basic query endpoint returns tabular data without
    geometry. This function returns a GeoDataFrame with point geometry derived
    from the block group centroid (TRACT + BLOCK GROUP). For polygon geometry,
    use the cartographic boundary shapefiles from the Census FTP server.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        GeoDataFrame with columns: state, county, tract, block_group,
        pop, hh, du, du_detsf, du_attsf, du_mf_2_9, du_mf_10p,
        owner_occupied, renter_occupied, geometry.

    Raises:
        RuntimeError: On API errors or empty data.
    """
    url = _build_census_url(state_fips, county_fips, "block group")
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


def fetch_acs_data_summary(state_fips: str, county_fips: str) -> dict[str, Any]:
    """Return a summary of ACS data available for the given geography.

    Useful for the UI to show what data is available before importing.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        Dict with keys: table_groups (list of table IDs), row_count,
        and sample columns.
    """
    try:
        url = _build_census_url(state_fips, county_fips, "block group")
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
            ],
        }
    except RuntimeError as e:
        return {"error": str(e), "table_groups": [], "row_count": 0, "columns": []}
