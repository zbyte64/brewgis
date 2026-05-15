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

# National proportions for splitting ACS DU subtypes
_DU_MF_2_9_TO_MF2TO4_RATIO = 0.40  # 40% of 2-9 units → 2-4 units


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
    """Fetch ACS data, join with TIGER BG geometry, and write to ``census.acs_block_group`` via a single SQL statement.

    Replaces the previous pandas→geopandas round-trip with an
    all-SQL approach. Derived columns, safe percentage computations,
    and DU sub-type splitting are all computed in PostgreSQL.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: ACS data year (default 2022).

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If the query returns no data.
    """
    detsf_sl_ratio = _DU_DETSF_TO_SL_RATIO
    sl_density_threshold = _SL_DENSITY_THRESHOLD
    mf_2_9_to_mf2to4_ratio = _DU_MF_2_9_TO_MF2TO4_RATIO

    sql = text("""
        CREATE TABLE census.acs_block_group AS
        WITH raw_derived AS (
            SELECT
                a.state || a.county || a.tract || a."block_group" AS geoid,
                ST_Multi(ST_GeomFromText(tbg.geometry, 4326)) AS geometry,
                COALESCE(a.b01001_001_e, 0)::numeric AS pop,
                COALESCE(a.b25003_001_e, 0)::numeric AS hh,
                COALESCE(a.b25024_001_e, 0)::numeric AS du,
                -- DU types
                COALESCE(a.b25024_002_e, 0)::numeric AS du_detsf,
                COALESCE(a.b25024_003_e, 0)::numeric AS du_attsf,
                (COALESCE(a.b25024_004_e, 0) + COALESCE(a.b25024_005_e, 0)
                    + COALESCE(a.b25024_006_e, 0))::numeric AS du_mf_2_9,
                (COALESCE(a.b25024_007_e, 0) + COALESCE(a.b25024_008_e, 0)
                    + COALESCE(a.b25024_009_e, 0))::numeric AS du_mf_10p,
                -- Tenure
                COALESCE(a.b25003_002_e, 0)::numeric AS owner_occupied,
                COALESCE(a.b25003_003_e, 0)::numeric AS renter_occupied,
                -- Income
                COALESCE(a.b19013_001_e, 0)::numeric AS median_income,
                -- Rent burden
                COALESCE(a.b25070_001_e, 0)::numeric AS rent_total,
                (COALESCE(a.b25070_007_e, 0) + COALESCE(a.b25070_008_e, 0)
                 + COALESCE(a.b25070_009_e, 0) + COALESCE(a.b25070_010_e, 0))::numeric AS renter_cost_burdened,
                -- Owner cost burden
                (COALESCE(a.b25091_005_e, 0) + COALESCE(a.b25091_006_e, 0)
                    + COALESCE(a.b25091_007_e, 0) + COALESCE(a.b25091_011_e, 0)
                    + COALESCE(a.b25091_012_e, 0)
                    + COALESCE(a.b25091_013_e, 0))::numeric AS owner_cost_burdened,
                -- Demographics
                COALESCE(a.b03002_001_e, 0)::numeric AS total_population,
                COALESCE(a.b03002_002_e, 0)::numeric AS white_alone_pop,
                -- Education
                COALESCE(a.b15003_001_e, 0)::numeric AS edu_total,
                (COALESCE(a.b15003_022_e, 0) + COALESCE(a.b15003_023_e, 0)
                 + COALESCE(a.b15003_024_e, 0) + COALESCE(a.b15003_025_e, 0))::numeric AS college_educated
            FROM public.acs_raw a
            JOIN public.tiger_block_groups tbg
                ON tbg.geoid = a.state || a.county || a.tract || a."block_group"
            WHERE a.year = :year
              AND a.state = :state_fips
              AND a.county = :county_fips
        ),
        derived_with_pcts AS (
            SELECT
                *,
                -- Safe percentages
                CASE WHEN rent_total > 0
                    THEN ROUND(renter_cost_burdened / NULLIF(rent_total, 0) * 100.0, 2)
                    ELSE 0 END AS rent_burden_pct,
                CASE WHEN hh > 0
                    THEN ROUND((owner_cost_burdened + renter_cost_burdened) / NULLIF(hh, 0) * 100.0, 2)
                    ELSE 0 END AS cost_burden_pct,
                CASE WHEN total_population > 0
                    THEN ROUND((total_population - white_alone_pop) / NULLIF(total_population, 0) * 100.0, 2)
                    ELSE 0 END AS pct_minority,
                CASE WHEN edu_total > 0
                    THEN ROUND(college_educated / NULLIF(edu_total, 0) * 100.0, 2)
                    ELSE 0 END AS pct_college_educated,
                -- DU sub-type splits (fixed ratios)
                ROUND(du_mf_2_9 * :mf_2_9_to_mf2to4_ratio, 1) AS du_mf2to4,
                ROUND(du_mf_2_9 * (1 - :mf_2_9_to_mf2to4_ratio) + du_mf_10p, 1) AS du_mf5p,
                -- Density-calibrated single-family lot split
                CASE
                    WHEN du_detsf > 0 AND geometry IS NOT NULL AND ST_IsValid(geometry)
                    THEN LEAST(1.0, GREATEST(0.0,
                        1.0 / (1.0 + EXP(-0.5 * (
                            (du_detsf / NULLIF(ST_Area(ST_Transform(geometry, 6933)) / 4046.86, 0))
                            - :sl_density_threshold
                        )))
                    ))
                    ELSE :detsf_sl_ratio
                END AS sl_ratio
            FROM raw_derived
        )
        SELECT
            geoid,
            geometry,
            pop,
            hh,
            du,
            du_attsf,
            du_mf2to4,
            du_mf5p,
            ROUND(du_mf2to4 + du_mf5p, 1) AS du_mf,
            ROUND(du_detsf * sl_ratio, 1) AS du_detsf_sl,
            ROUND(du_detsf * (1 - sl_ratio), 1) AS du_detsf_ll,
            owner_occupied,
            renter_occupied,
            median_income,
            rent_burden_pct,
            cost_burden_pct,
            total_population,
            pct_minority,
            pct_college_educated
        FROM derived_with_pcts
    """)

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS census"))
        conn.execute(text("DROP TABLE IF EXISTS census.acs_block_group"))
        conn.execute(
            sql,
            {
                "year": year,
                "state_fips": state_fips,
                "county_fips": county_fips,
                "detsf_sl_ratio": detsf_sl_ratio,
                "sl_density_threshold": sl_density_threshold,
                "mf_2_9_to_mf2to4_ratio": mf_2_9_to_mf2to4_ratio,
            },
        )
        conn.commit()

        result = conn.execute(
            text("SELECT COUNT(*) FROM census.acs_block_group")
        ).scalar()
        row_count = result or 0

    if row_count == 0:
        msg = (
            f"No ACS block-group data returned for "
            f"{state_fips}/{county_fips} year {year}"
        )
        raise RuntimeError(msg)
    return row_count
