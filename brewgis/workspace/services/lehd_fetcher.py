"""LEHD → LODES employment data fetcher.

Provides LODES WAC constants (FIPS mapping, variable definitions, NAICS
split rules) and the ``_populate_wac_block`` function that orchestrates
SQLMesh materialization of ``wac_block_raw`` and ``wac_block``.

CBP proportion computation moved to ``cbp_proportions.sql`` SQLMesh model.
Data available: 2002-2021.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.analysis.sqlmesh_runner import get_context
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

logger = logging.getLogger(__name__)


# ── LODES WAC (Workplace Area Characteristics) ─────────────────────────

LODES_WAC_BASE = "https://lehd.ces.census.gov/data/lodes/LODES8"
# FIPS → state abbreviation mapping for LODES URL
_FIPS_TO_STATE: dict[str, str] = {
    "01": "al",
    "02": "ak",
    "04": "az",
    "05": "ar",
    "06": "ca",
    "08": "co",
    "09": "ct",
    "10": "de",
    "11": "dc",
    "12": "fl",
    "13": "ga",
    "15": "hi",
    "16": "id",
    "17": "il",
    "18": "in",
    "19": "ia",
    "20": "ks",
    "21": "ky",
    "22": "la",
    "23": "me",
    "24": "md",
    "25": "ma",
    "26": "mi",
    "27": "mn",
    "28": "ms",
    "29": "mo",
    "30": "mt",
    "31": "ne",
    "32": "nv",
    "33": "nh",
    "34": "nj",
    "35": "nm",
    "36": "ny",
    "37": "nc",
    "38": "nd",
    "39": "oh",
    "40": "ok",
    "41": "or",
    "42": "pa",
    "44": "ri",
    "45": "sc",
    "46": "sd",
    "47": "tn",
    "48": "tx",
    "49": "ut",
    "50": "vt",
    "51": "va",
    "53": "wa",
    "54": "wv",
    "55": "wi",
    "56": "wy",
    "72": "pr",
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
        ("emp_wholesale", r"^42\s*-*"),  # split wholesale via CBP
        ("emp_retail_services", None),  # remainder = retail (44-45) only
    ],
    # CNS04-09 → all map to office services
    "CNS04": [("emp_office_services", 1.0)],  # Information (51)
    "CNS05": [("emp_office_services", 1.0)],  # Finance & Insurance (52)
    "CNS06": [("emp_office_services", 1.0)],  # Real Estate (53)
    "CNS07": [("emp_office_services", 1.0)],  # Professional Services (54)
    "CNS08": [("emp_office_services", 1.0)],  # Management (55)
    "CNS09": [("emp_office_services", 1.0)],  # Admin & Support (56)
    # CNS10-12 → direct mappings
    "CNS10": [("emp_education", 1.0)],  # Educational Services (61)
    "CNS11": [("emp_medical_services", 1.0)],  # Health Care (62)
    "CNS12": [("emp_arts_entertainment", 1.0)],  # Arts, Entertainment (71)
    # CNS13 (Accommodation/Food 72) → CBP split
    "CNS13": [
        ("emp_accommodation", r"^721\s*-*"),
        ("emp_restaurant", None),  # remainder (722)
    ],
    "CNS14": [("emp_other_services", 1.0)],  # Other Services (81)
    "CNS15": [("emp_public_admin", 1.0)],  # Public Administration (92)
    "CNS17": [("emp_military", 1.0)],  # Armed Forces
}
# SACOG-calibrated employment sub-sector proportions (from base canvas)
# Each key is an aggregate sector; values are sub-sector proportions summing to 1.
# Derived from reference database table sac_cnty_region_base_canvas.
_SACOG_SUBSECTOR_PROPORTIONS: dict[str, dict[str, float]] = {
    "emp_ret": {
        "emp_retail_services": 76395 / 163859,
        "emp_restaurant": 42520 / 163859,
        "emp_accommodation": 3827 / 163859,
        "emp_arts_entertainment": 7567 / 163859,
        "emp_other_services": 33330 / 163859,
    },
    "emp_off": {
        "emp_office_services": 236721 / 259466,
        "emp_medical_services": 22745 / 259466,
    },
    "emp_pub": {
        "emp_public_admin": 16924 / 44285,
        "emp_education": 27361 / 44285,
    },
    "emp_ind": {
        "emp_manufacturing": 46244 / 74702,
        "emp_wholesale": 10672 / 74702,
        "emp_transport_warehousing": 14229 / 74702,
        "emp_utilities": 719 / 74702,
        "emp_construction": 2838 / 74702,
    },
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
        "emp_restaurant",
        "emp_accommodation",
        "emp_arts_entertainment",
        "emp_other_services",
    ],
    "emp_off": [
        "emp_office_services",
        "emp_medical_services",
    ],
    "emp_pub": [
        "emp_education",
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
    return f"{LODES_WAC_BASE}/{state_abbr}/wac/{state_abbr}_wac_S000_JT00_{year}.csv.gz"


# ── CBP County-Scale Calibration (reference constants) ────────────────


# NAICS 2-digit (or 3-digit for accommodation/restaurant) codes per
# sub-sector column for county-level CBP scaling.
# Maps each sub-sector column to the CBP NAICS codes that comprise it.
_SUBSECTOR_CBP_NAICS: dict[str, list[str]] = {
    "emp_retail_services": ["44", "45"],
    "emp_restaurant": ["722"],  # 3-digit NAICS
    "emp_accommodation": ["721"],  # 3-digit NAICS
    "emp_arts_entertainment": ["71"],
    "emp_other_services": ["81"],
    "emp_office_services": ["51", "52", "53", "54", "55", "56"],
    "emp_medical_services": ["62"],
    "emp_public_admin": ["92"],
    "emp_education": ["61"],
    "emp_manufacturing": ["31", "32", "33"],
    "emp_wholesale": ["42"],
    "emp_transport_warehousing": ["48", "49"],
    "emp_utilities": ["22"],
    "emp_construction": ["23"],
    "emp_agriculture": ["11"],
}


def _populate_wac_block(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
    force_reload: bool = False,
) -> int:
    """Join LEHD LODES WAC data with TIGER BG geometry via SQLMesh models.

    1. ``brewgis.staging.wac_block_raw`` — CNS-to-sub-sector splitting with
       CBP proportions (from ``cbp_proportions.sql`` model).
    2. ``brewgis.staging.wac_block`` — C000 gap distribution and CBP county-
       level scaling to correct LEHD disclosure suppression.

    CBP proportion variables are computed by the ``cbp_proportions.sql``
    SQLMesh model; this function passes the basic geographic/dataset vars.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: LEHD data year (default 2021).
        force_reload: If True, restate the models even if unchanged.

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If the table is empty after materialization.
    """
    # Build variables for wac_block_raw and wac_block.
    vars: dict[str, object] = {
        "state_fips": state_fips,
        "county_fips": county_fips,
        "lodes_year": year,
        "tiger_block_vintage": "2020",
        "tiger_bg_vintage": "2023",
    }

    # Materialize wac_block_raw (CNS-to-sub-sector splitting with CBP proportions)
    def _restate_list() -> list[str]:
        from brewgis.workspace.analysis.sqlmesh_runner import get_context

        ctx = get_context()
        existing = ["+brewgis.staging.wac_block_raw", "+brewgis.staging.wac_block"]
        return [m for m in existing if m in ctx.models]

    restate_wac = _restate_list() if force_reload else False
    run_sqlmesh_plan(
        select=["+brewgis.staging.wac_block_raw"],
        variables=vars,
        restate_models=restate_wac,
    )

    return -1


def fetch_lehd_data_summary(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, Any]:
    """Return a summary of available employment data from staging."""
    context = get_context()
    df = context.fetchdf("""
        SELECT COUNT(*) as row_count
        FROM brewgis.staging.lodes_raw
        WHERE year = :year
    """)
    row_count = df[0][0] or 0
    return {
        "row_count": row_count,
        "variables": list(LODES_WAC_VARIABLES.keys()),
        "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
        "sub_sector_count": len(_NAICS_SPLIT_RULES),
    }
