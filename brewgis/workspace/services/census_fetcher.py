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

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

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

# SACOG-calibrated sigmoid steepness for small-lot vs large-lot single-family
# Reference fit: k=4.5, t=8.4. Default k=0.5 is the national default.
# Fit derived from SACOG v1 reference dataset: density vs sl_ratio per parcel.
_SACOG_K_STEEPNESS: float = 4.5
_BREWGIS_K_STEEPNESS_ENV_VAR: str = "BREWGIS_K_STEEPNESS"
_K_STEEPNESS: float
try:
    _raw_k = float(os.environ.get(_BREWGIS_K_STEEPNESS_ENV_VAR, "0.5"))
    _K_STEEPNESS = max(0.01, _raw_k)
except (ValueError, TypeError):
    _K_STEEPNESS = 0.5


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
        row_count = result or 0

    return {
        "table_groups": list(ACS_TABLE_GROUPS.keys()),
        "row_count": row_count,
        "columns": [
            "pop",
            "hh",
            "du",
            "du_detsf",
            "du_attsf",
            "du_2",
            "du_3_4",
            "du_5_9",
            "du_10p",
            "du_mf2to4",
            "du_mf5p",
            "du_detsf_sl",
            "du_detsf_ll",
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
    """Fetch ACS data, join with TIGER BG geometry via the ``acs_block_group`` dbt model.

    Invokes dbt to materialize ``census.acs_block_group`` with derived
    columns, safe percentage computations, and DU sub-type splitting.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If dbt fails or the table is empty.
    """
    dbt_vars: dict[str, object] = {
        "source_schema": "public",
        "acs_raw_table": "acs_raw",
        "tiger_bg_table": "tiger_block_groups",
        "year": year,
        "state_fips": state_fips,
        "county_fips": county_fips,
        "detsf_sl_ratio": _DU_DETSF_TO_SL_RATIO,
        "sl_density_threshold": _SL_DENSITY_THRESHOLD,
        "k_steepness": _K_STEEPNESS,
        "tiger_bg_vintage": "2013",
    }

    result = run_sqlmesh_plan(environment="brewgis_prod", select=["brewgis.staging.acs_block_group"], skip_tests=True)
    if not result.success:
        msg = f"SQLMesh acs_block_group failed: {result.error}"
        raise RuntimeError(msg)

    engine = get_engine()
    with engine.connect() as conn:
        row_count = (
            conn.execute(text("SELECT COUNT(*) FROM census.acs_block_group")).scalar()
            or 0
        )

    if row_count == 0:
        msg = (
            f"No ACS block-group data returned for "
            f"{state_fips}/{county_fips} year {year}"
        )
        raise RuntimeError(msg)
    return row_count
