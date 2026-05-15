"""Census ACS demographics fetcher — reads ACS data from PostGIS staging tables.

Data is loaded by the census dlt pipeline into ``public.acs_raw`` and polygon
geometry sourced from ``public.tiger_block_groups`` (TIGER/Line BG dlt pipeline).

Supported tables (mapped to base canvas columns):
- B01001: Sex by Age (pop)
- B25003: Tenure (hh — occupied housing units)
- B25024: Units in Structure (du, du_detsf*, du_attsf, du_mf*)
- B25008: Total Population in Occupied Housing Units (pop/hh ratio check)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import geopandas as gpd
import numpy as np
from shapely import wkt as geom

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)


def _census_api_key() -> str:
    """Return Census API key from Django settings, or empty string."""
    from django.conf import settings as django_settings

    return django_settings.CENSUS_API_KEY or ""


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
# 83% large-lot / 17% small-lot (ratio ~0.17), though this varies by
# jurisdiction within the county.
_DU_DETSF_TO_SL_RATIO: float
try:
    _raw = float(os.environ.get("BREWGIS_DETSF_SL_RATIO", "0.40"))
    _DU_DETSF_TO_SL_RATIO = max(0.0, _raw)
except (ValueError, TypeError):
    _DU_DETSF_TO_SL_RATIO = 0.40
# SACOG-calibrated density threshold for small-lot vs large-lot single-family
# SACOG convention uses ~1/8 acre (5,445 sqft) lot size as threshold
_SACOG_SL_DENSITY_THRESHOLD: float = 8.0  # DU per residential acre
_BREWGIS_SL_DENSITY_THRESHOLD_ENV_VAR: str = "BREWGIS_SL_DENSITY_THRESHOLD"
_SL_DENSITY_THRESHOLD: float
try:
    _raw_threshold = float(
        os.environ.get(
            _BREWGIS_SL_DENSITY_THRESHOLD_ENV_VAR, str(_SACOG_SL_DENSITY_THRESHOLD)
        )
    )
    _SL_DENSITY_THRESHOLD = max(0.0, _raw_threshold)
except (ValueError, TypeError):
    _SL_DENSITY_THRESHOLD = _SACOG_SL_DENSITY_THRESHOLD

# National proportions for splitting ACS DU subtypes
_DU_MF_2_9_TO_MF2TO4_RATIO = 0.40  # 40% of 2-9 units → 2-4 units


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
        # Density-calibrated SL/LL split using block-group geometry
        bg_geo = block_groups.geometry
        has_crs = block_groups.crs is not None
        if bg_geo is not None and not bg_geo.is_empty.all() and has_crs:
            bg_6933 = block_groups.to_crs("EPSG:6933")
            area_acres = bg_6933.geometry.area / 4046.86
            density = block_groups["du_detsf"].fillna(0.0) / area_acres.clip(lower=0.01)
            # Sigmoid around threshold for smooth transition
            sl_ratio = 1.0 / (1.0 + np.exp(-0.5 * (density - _SL_DENSITY_THRESHOLD)))
            block_groups["du_detsf_sl"] = (
                block_groups["du_detsf"].fillna(0.0) * sl_ratio
            ).round(1)
            block_groups["du_detsf_ll"] = (
                block_groups["du_detsf"].fillna(0.0) * (1 - sl_ratio)
            ).round(1)
        else:
            block_groups["du_detsf_sl"] = (
                block_groups["du_detsf"].fillna(0.0) * _DU_DETSF_TO_SL_RATIO
            ).round(1)
            block_groups["du_detsf_ll"] = (
                block_groups["du_detsf"].fillna(0.0) * (1 - _DU_DETSF_TO_SL_RATIO)
            ).round(1)
        block_groups.drop(columns=["du_detsf"], inplace=True, errors="ignore")
    else:
        block_groups["du_detsf_sl"] = 0.0
        block_groups["du_detsf_ll"] = 0.0

    return block_groups


def fetch_acs_block_group_polygons(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
    use_cache: bool = True,  # kept for backward compat, ignored
) -> gpd.GeoDataFrame:
    """Fetch ACS demographics with polygon geometry from staging tables.

    Reads ACS attributes from ``public.acs_raw`` staging table (loaded by the
    census dlt pipeline) and polygon geometry from ``public.tiger_block_groups``
    (loaded by the TIGER/Line BG dlt pipeline), then joins on GEOID.

    Derived columns and column mapping are applied post-join.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).
        use_cache: Kept for backward compatibility, ignored.

    Returns:
        GeoDataFrame with polygon geometry, geoid, and all
        demographic columns mapped to BaseCanvasSchema names.
    """
    engine = get_engine()

    query = text("""
        SELECT a.*, t.geometry
        FROM public.acs_raw a
        JOIN public.tiger_block_groups t
            ON t.geoid = a.state || a.county || a.tract || a."block_group"
        WHERE a.year = :year
          AND a.state = :state_fips
          AND a.county = :county_fips
    """)

    with engine.connect() as conn:
        rows = conn.execute(
            query,
            {"year": year, "state_fips": state_fips, "county_fips": county_fips},
        ).fetchall()
        columns = list(rows[0]._fields) if rows else []
        data = [dict(zip(columns, row, strict=False)) for row in rows]

    if not data:
        logger.warning(
            "No ACS data found in staging for %s/%s year %s",
            state_fips,
            county_fips,
            year,
        )
        return gpd.GeoDataFrame()

    # Parse WKT geometry column
    wkt_geoms = []
    for row in data:
        wkt_val = row.pop("geometry", None)
        if wkt_val:
            wkt_geoms.append(geom.loads(wkt_val))
        else:
            wkt_geoms.append(None)

    # Compute derived columns from raw ACS variables
    records = []
    for row in data:
        int_row = {}
        for var in _all_vars():
            try:
                int_row[var] = int(row.get(var, 0)) if row.get(var) is not None else 0
            except (ValueError, TypeError):
                int_row[var] = 0
        derived = _compute_derived_columns(int_row)
        record = {
            "state": row.get("state", ""),
            "county": row.get("county", ""),
            "tract": row.get("tract", ""),
            "block_group": row.get("block_group", ""),
        }
        record.update(derived)
        geoid = f"{record['state']}{record['county']}{record['tract']}{record['block_group']}"
        record["geoid"] = geoid
        records.append(record)

    if not records:
        return gpd.GeoDataFrame()

    gdf: gpd.GeoDataFrame = gpd.GeoDataFrame(
        records, geometry=wkt_geoms, crs="EPSG:4326"
    )
    gdf = gdf[~gdf.geometry.isna()]
    return _apply_acs_column_mapping(gdf)


def fetch_acs_data_summary(
    state_fips: str, county_fips: str, year: int = 2022
) -> dict[str, Any]:
    """Return a summary of ACS data available in the staging table.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).

    Returns:
        Dict with keys: table_groups (list of table IDs), row_count,
        and columns (list of derived column names).
    """
    engine = get_engine()

    query = text("""
        SELECT COUNT(*) as row_count
        FROM public.acs_raw
        WHERE state = :state_fips
          AND county = :county_fips
          AND year = :year
    """)
    with engine.connect() as conn:
        result = conn.execute(
            query,
            {
                "state_fips": state_fips,
                "county_fips": county_fips,
                "year": year,
            },
        ).scalar()
        row_count = result if result else 0

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


def _populate_acs_block_group(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
) -> int:
    """Fetch ACS data, join with TIGER BG geometry, and write to ``census.acs_block_group``.

    The pipeline's ``_allocate_demographics`` step reads from
    ``census.acs_block_group``.  This helper creates it by running the
    existing ``fetch_acs_block_group_polygons`` query and persisting the
    result as a PostGIS table.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If the query returns no data.
    """
    gdf = fetch_acs_block_group_polygons(state_fips, county_fips, year)

    if gdf.empty:
        raise RuntimeError(
            f"No ACS block-group data returned for {state_fips}/{county_fips} year {year}"
        )

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS census"))
        conn.commit()

    gdf.to_postgis(
        "acs_block_group",
        engine,
        schema="census",
        if_exists="replace",
        index=False,
        dtype={"geometry": "geometry(MultiPolygon, 4326)"},
    )

    return len(gdf)
