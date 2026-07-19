"""LEHD → LODES employment data fetcher with CBP-based sub-sector splitting.

Downloads LODES (Longitudinal Employer-Household Dynamics) Workplace Area
Characteristics (WAC) data from the CES FTP server, and County Business
Patterns (CBP) data from the Census API for detailed sub-sector proportional
splitting.

Data available: 2002-2021.
See https://lehd.ces.census.gov/data/lodes/LODES7/ for documentation.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import deal
import pandas as pd
import requests
from django.conf import settings as django_settings

from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

CACHE_DIR: Path = django_settings.DATA_DOWNLOAD_CACHE_DIR
"""Disk cache directory for API responses."""


QCEW_MIN_YEAR: int = 2014
"""Earliest year for which QCEW area slice data is available."""


def _census_api_key() -> str:
    """Return Census API key from Django settings, or empty string."""
    from django.conf import settings as django_settings

    if not django_settings.CENSUS_API_KEY:
        raise RuntimeError("CENSUS_API_KEY is required")

    return django_settings.CENSUS_API_KEY


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


# ── CBP Proportion Computation ────────────────────────────────────────


def _parse_cbp_naics_emp(
    rows: list[list[str]],
    header: list[str],
) -> dict[str, float]:
    """Parse CBP API rows into a dict of NAICS code to employment count.

    Handles both ``NAICS2017`` (year >= 2017) and ``NAICS2007`` (year < 2017)
    column names, since the CBP API returns the column matching the NAICS
    taxonomy year.
    """
    # Resolve NAICS column: API returns NAICS2017 for year >= 2017,
    # NAICS2007 for year < 2017. Fall back gracefully if neither is present.
    naics_col = (
        "NAICS2017"
        if "NAICS2017" in header
        else "NAICS2007"
        if "NAICS2007" in header
        else ""
    )
    naics_emp: dict[str, float] = {}
    for row in rows:
        raw = dict(zip(header, row, strict=False))
        naics_raw = raw.get(naics_col, "").strip() if naics_col else ""
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


_COMBINED_NAICS_CODES: frozenset[str] = frozenset(
    {
        "3133",  # NAICS 31-33 (manufacturing)
        "4445",  # NAICS 44-45 (retail trade)
        "4849",  # NAICS 48-49 (transportation/warehousing)
    }
)


def _group_naics_by_prefix(
    naics_emp: dict[str, float],
    width: int = 2,
) -> dict[str, float]:
    """Group NAICS employment counts by prefix of ``width`` characters.

    Only counts parent-level rows.  Codes are expected to be already
    dash-stripped by _parse_cbp_naics_emp (pure digit strings).

    At width=2: counts exact 2-digit codes (e.g. "23", "44") and
    4-digit combined codes in _COMBINED_NAICS_CODES ("4445" → prefix "44").
    Excludes 3-digit sub-breakdowns (e.g. "236" under "23") and all
    other longer codes.

    At width=3: counts exact 3-digit codes only.
    """
    grouped: dict[str, float] = {}
    for code, val in naics_emp.items():
        if len(code) < width:
            continue
        # Parent-level: exact-width code, or known combined code at width=2
        if len(code) == width or (width == 2 and code in _COMBINED_NAICS_CODES):
            prefix = code[:width]
            grouped[prefix] = grouped.get(prefix, 0.0) + val
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


def _compute_cbp_proportions(
    raw_data: list[list[str]],
) -> dict[str, float]:
    """Compute within-sector proportions from raw CBP API response data.

    Pure function with no I/O — takes parsed CBP JSON data (header + rows)
    and returns the proportion dict.  The raw_data must have at least a header
    row; empty responses produce an empty dict.

    Args:
        raw_data: CBP API response as list of lists, where the first element
            is the header row (``["EMP", "NAICS2017", ...]``) and subsequent
            rows are data rows.

    Returns:
        Dict mapping NAICS code prefix to proportion of employment within
        that NAICS sector.
    """
    if len(raw_data) < 2:  # noqa: PLR2004
        return {}

    header = raw_data[0]
    rows = raw_data[1:]
    naics_emp = _parse_cbp_naics_emp(rows, header)

    sector_emp = _group_naics_by_prefix(naics_emp, 2)
    naics3_emp = _group_naics_by_prefix(naics_emp, 3)

    proportions: dict[str, float] = {}

    # CNS01 parent: NAICS 11, 21, 23
    goods_prefixes = ["11", "21", "23"]
    goods_total = sum(sector_emp.get(p, 0) for p in goods_prefixes)
    if goods_total > 0:
        for pfx in goods_prefixes:
            proportions[pfx] = _cbp_proportion_in(pfx, goods_prefixes, sector_emp)
    else:
        proportions["11"] = 0.05
        proportions["21"] = 0.02
        proportions["23"] = 0.93

    # CNS03 parent: NAICS 22, 42, 44, 45, 48, 49
    ttu_prefixes = ["22", "42", "44", "45", "48", "49"]
    ttu_total = sum(sector_emp.get(p, 0) for p in ttu_prefixes)
    if ttu_total > 0:
        for pfx in ttu_prefixes:
            proportions[pfx] = _cbp_proportion_in(pfx, ttu_prefixes, sector_emp)
    else:
        proportions["22"] = 0.02
        proportions["42"] = 0.10
        proportions["44"] = 0.54
        proportions["45"] = 0.28
        proportions["48"] = 0.04
        proportions["49"] = 0.02

    # CNS13 parent: NAICS 721, 722 (3-digit accommodation/food)
    acc_food_total = naics3_emp.get("721", 0) + naics3_emp.get("722", 0)
    if acc_food_total > 0:
        proportions["721"] = naics3_emp.get("721", 0) / acc_food_total
        proportions["722"] = naics3_emp.get("722", 0) / acc_food_total
    else:
        proportions["721"] = 0.4
        proportions["722"] = 0.6

    return proportions


# ── Shared CBP Data Cache ──────────────────────────────────────────────


def _fetch_cbp_data(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
    ignore_cache: bool = False,
) -> list[list[str]]:
    """Fetch CBP data from Census API, caching to disk.

    Returns the raw JSON response (header + data rows) for further processing.
    Both _build_cbp_proportions and _compute_all_cbp_totals share this cache.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: CBP data year (default 2021).
        ignore_cache: If True, re-fetch from API even if cached copy exists.

    Returns:
        Raw CBP API response as list of lists (first element is header row).

    Raises:
        RuntimeError: If CBP API returns no data rows.
    """
    state_fips_clean = state_fips.zfill(2)
    county_fips_clean = county_fips.zfill(3)
    naics_year = 2017 if year >= 2017 else 2007
    dl_path = (
        CACHE_DIR
        / "cbp_proportions"
        / str(year)
        / state_fips_clean
        / f"{county_fips_clean}.json"
    )
    dl_path.parent.mkdir(exist_ok=True, parents=True)
    if ignore_cache or not dl_path.exists():
        key = _census_api_key()
        key_param = f"&key={key}" if key else ""
        url = (
            f"https://api.census.gov/data/{year}/cbp"
            f"?get=EMP,NAICS{naics_year}&for=county:{county_fips_clean}"
            f"&in=state:{state_fips_clean}{key_param}"
        )
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        raw_data: list[list[str]] = response.json()
        dl_path.write_text(json.dumps(raw_data))
        logger.info(
            "CBP data fetched and cached for %s/%s year %s",
            state_fips_clean,
            county_fips_clean,
            year,
        )
    else:
        raw_data = json.loads(dl_path.read_text())
        logger.info(
            "CBP data loaded from cache for %s/%s year %s",
            state_fips_clean,
            county_fips_clean,
            year,
        )
    if len(raw_data) < 2:
        msg = "CBP API returned no data rows."
        raise RuntimeError(msg)
    return raw_data


def _build_cbp_proportions(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
    ignore_cache: bool = False,
) -> dict[str, float]:
    """Fetch CBP employment by NAICS code and compute within-sector proportions.

    Downloads County Business Patterns data for the given county, groups NAICS
    employment at the 2-6 digit level, and returns proportion of employment
    within each NAICS-parent group that each sub-sector accounts for.

    The raw API response is cached to disk under ``CACHE_DIR / "cbp_proportions"``.
    Pass ``ignore_cache=True`` to force a fresh fetch.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).
        ignore_cache: If True, re-fetch from API even if cached copy exists.

    Returns:
        Dict mapping NAICS code prefix to proportion of employment within
        that NAICS sector. For example: "11" -> 0.15 (agriculture's share
        of goods-producing sectors).

    Raises:
        RuntimeError: If CBP API returns no data rows.
    """
    state_fips_clean = state_fips.zfill(2)
    county_fips_clean = county_fips.zfill(3)
    raw_data = _fetch_cbp_data(state_fips, county_fips, year, ignore_cache)

    result = _compute_cbp_proportions(raw_data)

    # Log fallback warnings (the pure function can't log)
    sector_emp = _group_naics_by_prefix(
        _parse_cbp_naics_emp(raw_data[1:], raw_data[0]), 2
    )
    goods_prefixes = ["11", "21", "23"]
    goods_total = sum(sector_emp.get(p, 0) for p in goods_prefixes)
    if goods_total == 0:
        logger.warning(
            "CBP CNS01 data unavailable for %s/%s year %s — using national-average fallback proportions.",
            state_fips_clean,
            county_fips_clean,
            year,
        )
    ttu_prefixes = ["22", "42", "44", "45", "48", "49"]
    ttu_total = sum(sector_emp.get(p, 0) for p in ttu_prefixes)
    if ttu_total == 0:
        logger.warning(
            "CBP CNS03 data unavailable for %s/%s year %s — using national-average fallback proportions.",
            state_fips_clean,
            county_fips_clean,
            year,
        )
    naics3_emp = _group_naics_by_prefix(
        _parse_cbp_naics_emp(raw_data[1:], raw_data[0]), 3
    )
    acc_food_total = naics3_emp.get("721", 0) + naics3_emp.get("722", 0)
    if acc_food_total == 0:
        logger.warning(
            "CBP CNS13 (accommodation/food) data unavailable for %s/%s year %s — using fallback proportions.",
            state_fips_clean,
            county_fips_clean,
            year,
        )

    return result


# ── CBP County-Scale Calibration ──────────────────────────────────────


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
    "emp_extraction": ["21"],
}


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

    # Ensure non-negative values (vaa does not wrap bare lambdas, so deal.ensure is unusable here)
    for _v in result.values():
        assert _v >= 0, f"Negative value in _apply_naics_splits result: {_v}"
    return result


@deal.ensure(lambda _row, result: all(v >= 0 for v in result.values()))
def _apply_sacog_calibrated_splits(row: dict[str, float]) -> dict[str, float]:
    """Apply SACOG-calibrated sub-sector proportions to aggregate columns.

    Overrides CBP-based proportions with SACOG base canvas calibrated values
    for aggregate sectors that have sub-sector breakdowns.

    Args:
        row: Dict with aggregate employment columns (emp_ret, emp_off, etc.).

    Returns:
        Dict mapping sub-sector column name to the SACOG-calibrated value.
    """
    result: dict[str, float] = {}
    for agg_sector, sub_sectors in _SACOG_SUBSECTOR_PROPORTIONS.items():
        agg_val = row.get(agg_sector, 0.0)
        if agg_val > 0:
            for sub_col, proportion in sub_sectors.items():
                result[sub_col] = agg_val * proportion
    return result


# ── Aggregate Column Computation ──────────────────────────────────────


@deal.ensure(lambda _row, result: all(v >= 0 for v in result.values()))
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
) -> pd.DataFrame:
    """Fetch LODES WAC employment data from the lodes_raw staging table.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2021).

    Returns:
        pd.DataFrame with columns: geoid, emp, aggregate columns,
        sub-sector columns. No geometry.
    Raises:
        RuntimeError: On empty staging data.
    """
    engine = get_engine()
    query = text("""
        SELECT * FROM public.lodes_raw
        WHERE year = :year
          AND LEFT(w_geocode, 5) = :county_fips
    """)
    with engine.connect() as conn:
        result = conn.execute(
            query, {"year": year, "county_fips": state_fips + county_fips}
        )
        rows = result.fetchall()
        columns = list(result.keys())
        records_df = pd.DataFrame(dict(zip(columns, row, strict=False)) for row in rows)

    if records_df.empty:
        msg = f"No LODES data in staging table for year {year}."
        raise RuntimeError(msg)

    # Rename w_geocode to geoid
    records_df = records_df.rename(columns={"w_geocode": "geoid"})

    # Fetch CBP proportions once
    cbp_props = _build_cbp_proportions(state_fips, county_fips, year)
    # Validate CBP proportions: parent-group totals must be non-zero.
    # All-zero proportions mean the CBP API returned no usable data and
    # no fallback was generated — this is a data dependency failure.
    cns01_sum = (
        cbp_props.get("11", 0.0) + cbp_props.get("21", 0.0) + cbp_props.get("23", 0.0)
    )
    cns03_sum = (
        cbp_props.get("22", 0.0)
        + cbp_props.get("42", 0.0)
        + cbp_props.get("44", 0.0)
        + cbp_props.get("45", 0.0)
        + cbp_props.get("48", 0.0)
        + cbp_props.get("49", 0.0)
    )
    if cns01_sum <= 0 or cns03_sum <= 0:
        raise RuntimeError(
            f"CBP proportions unavailable for {state_fips}/{county_fips} year {year}: "
            f"CNS01 sum={cns01_sum:.3f} CNS03 sum={cns03_sum:.3f}. "
            "The Census CBP API returned no usable employment data. "
            "Ensure CENSUS_API_KEY is set and the requested year is available."
        )

    lodes_records: list[dict[str, Any]] = []
    for _, row in records_df.iterrows():
        geoid = str(row.get("geoid", ""))
        total_jobs = int(row.get("C000", 0)) if pd.notna(row.get("C000")) else 0

        cns_row: dict[str, int | float] = {}
        for cns_col in _NAICS_SPLIT_RULES:
            val = int(row.get(cns_col, 0)) if pd.notna(row.get(cns_col)) else 0
            cns_row[cns_col] = val

        subsectors = _apply_naics_splits(cns_row, cbp_props)
        aggregates = _compute_aggregate_employment(subsectors)

        record: dict[str, Any] = {"geoid": geoid}
        record.update(subsectors)
        record.update(aggregates)
        record["emp"] = total_jobs
        lodes_records.append(record)

    # SACOG region (Sacramento County, CA) override
    _IS_SACOG_REGION = state_fips == "06" and county_fips == "067"
    if _IS_SACOG_REGION:
        for record in lodes_records:
            sacog_subs = _apply_sacog_calibrated_splits(record)
            for col in sacog_subs:
                record[col] = sacog_subs[col]
            for col in ("emp_agriculture", "emp_extraction", "emp_military"):
                record[col] = 0.0

    if not lodes_records:
        msg = "No LODES records parsed."
        raise RuntimeError(msg)

    return pd.DataFrame(lodes_records)


def fetch_lehd_data_summary(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, Any]:
    """Return a summary of available employment data from staging."""
    engine = get_engine()
    query = text("""
        SELECT COUNT(*) as row_count
        FROM public.lodes_raw
        WHERE year = :year
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"year": year}).scalar()
        row_count = result or 0
    return {
        "row_count": row_count,
        "variables": list(LODES_WAC_VARIABLES.keys()),
        "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
        "sub_sector_count": len(_NAICS_SPLIT_RULES),
    }


def _compute_all_cbp_totals(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, float]:
    """Fetch CBP employment for ALL sub-sector columns from full county data.

    Uses the shared _fetch_cbp_data cache (same as _build_cbp_proportions).
    Extracts absolute totals from raw CBP data using _SUBSECTOR_CBP_NAICS
    mapping and validates critical aggregate groups are non-zero.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: CBP data year (default 2021).

    Returns:
        Dict mapping every sub-sector column name (except emp_military) to
        its CBP county-level employment total (float).

    Raises:
        RuntimeError: If CBP data is unavailable or if critical aggregate
            groups (emp_ind, emp_ret, emp_off) are all zero — indicating
            a data dependency failure.
    """
    sf = state_fips.zfill(2)
    cf = county_fips.zfill(3)
    raw_data = _fetch_cbp_data(state_fips, county_fips, year)
    naics_emp = _parse_cbp_naics_emp(raw_data[1:], raw_data[0])
    assert naics_emp
    sector_emp_2 = _group_naics_by_prefix(naics_emp, 2)
    sector_emp_3 = _group_naics_by_prefix(naics_emp, 3)

    cbp_totals: dict[str, float] = {}
    for sub_col, naics_codes in _SUBSECTOR_CBP_NAICS.items():
        total = 0.0
        for code in naics_codes:
            if len(code) == 2:
                total += sector_emp_2.get(code, 0)
            else:
                total += sector_emp_3.get(code, 0)
        cbp_totals[sub_col] = total

    # Validate critical aggregate groups are non-zero
    emp_ind_subs = [
        "emp_manufacturing",
        "emp_wholesale",
        "emp_transport_warehousing",
        "emp_utilities",
        "emp_construction",
    ]
    emp_ret_subs = [
        "emp_retail_services",
        "emp_restaurant",
        "emp_accommodation",
        "emp_arts_entertainment",
        "emp_other_services",
    ]
    emp_off_subs = ["emp_office_services", "emp_medical_services"]

    emp_ind_total = sum(cbp_totals[s] for s in emp_ind_subs)
    emp_ret_total = sum(cbp_totals[s] for s in emp_ret_subs)
    emp_off_total = sum(cbp_totals[s] for s in emp_off_subs)

    if emp_ind_total <= 0 or emp_ret_total <= 0 or emp_off_total <= 0:
        msg = (
            f"CBP county totals unavailable for critical sectors in "
            f"{sf}/{cf} year {year}: "
            f"emp_ind_total={emp_ind_total:.0f} "
            f"emp_ret_total={emp_ret_total:.0f} "
            f"emp_off_total={emp_off_total:.0f}. "
            "The Census CBP API returned no usable employment data for one or "
            "more critical sector groups. Ensure CENSUS_API_KEY is set and the "
            "requested year is available."
            f"{naics_emp}"
        )
        raise RuntimeError(msg)

    return cbp_totals


def _resolve_sacog_ratios() -> dict[str, float]:
    """Resolve SACOG-calibrated sub-sector ratio vars from _SACOG_SUBSECTOR_PROPORTIONS.

    Maps aggregate-level proportions to per-sub-sector dbt var names.
    Returns a flat dict of sacog_*_ratio var names to float values.
    """
    ratios: dict[str, float] = {}
    for agg_col, sub_props in _SACOG_SUBSECTOR_PROPORTIONS.items():
        for sub_col, ratio in sub_props.items():
            # dbt model wac_block_raw.sql expects names without emp_ prefix
            var_name = f"sacog_{sub_col.removeprefix('emp_')}_ratio"
            ratios[var_name] = ratio
    # Zero out agriculture, extraction, and military
    ratios["sacog_agriculture_ratio"] = 0.0
    ratios["sacog_extraction_ratio"] = 0.0
    ratios["sacog_military_ratio"] = 0.0
    return ratios


def _fetch_qcew_government_split(
    state_fips: str,
    county_fips: str,
    year: int = 2008,
    ignore_cache: bool = False,
) -> dict[str, float]:
    """Fetch QCEW government employment data and compute CNS18-20 fractions.

    Downloads BLS QCEW annual area slice for the specified county, filters for
    government-owned establishments (own_code 1/2/3) in education (NAICS 61),
    health (NAICS 62), and public administration (NAICS 92), and returns the
    employment fraction for each sub-sector.

    The raw API response is parsed and cached to disk under
    ``CACHE_DIR / "qcew_govt" / year / "{fips_5}.json"``.
    Pass ``ignore_cache=True`` to force a fresh fetch.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Data year (default 2008, the LEHD base year).
        ignore_cache: If True, re-fetch from API even if cached copy exists.

    Returns:
        Dict with keys ``edu_frac``, ``med_frac``, ``pub_frac`` summing to 1.0.

    Raises:
        RuntimeError: On network error, empty data, or zero total employment.
    """
    fips_5 = state_fips.zfill(2) + county_fips.zfill(3)
    qcew_year = max(year, QCEW_MIN_YEAR)
    dl_path = CACHE_DIR / "qcew_govt" / str(qcew_year) / f"{fips_5}.json"
    dl_path.parent.mkdir(exist_ok=True, parents=True)

    if ignore_cache or not dl_path.exists():
        url = f"https://data.bls.gov/cew/data/api/{qcew_year}/1/area/{fips_5}.csv"
        response = requests.get(url, timeout=120)
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))

        govt_edu = 0.0  # NAICS 611 — Educational Services
        govt_med = 0.0  # NAICS 622 — Hospitals
        govt_pub = 0.0  # NAICS 92 — Public Administration

        for row in reader:
            own_code = row.get("own_code", "")
            if own_code not in ("1", "2", "3"):
                continue
            agglvl_code = row.get("agglvl_code", "")
            if agglvl_code != "78":
                continue
            industry_code = row.get("industry_code", "")
            emp_str = (row.get("month1_emplvl") or "").strip()
            if not emp_str:
                continue
            try:
                emp = float(emp_str)
            except (ValueError, TypeError):
                continue

            if industry_code.startswith("611"):
                govt_edu += emp
            elif industry_code.startswith("622"):
                govt_med += emp
            elif industry_code.startswith("92"):
                govt_pub += emp

        result = {
            "govt_edu": govt_edu,
            "govt_med": govt_med,
            "govt_pub": govt_pub,
        }
        dl_path.write_text(json.dumps(result))
        logger.info(
            "QCEW government data fetched and cached for %s year %s",
            fips_5,
            year,
        )
    else:
        result = json.loads(dl_path.read_text())
        logger.info(
            "QCEW government data loaded from cache for %s year %s",
            fips_5,
            year,
        )

    total = result["govt_edu"] + result["govt_med"] + result["govt_pub"]
    if total <= 0:
        msg = (
            f"QCEW government employment total is zero for {fips_5} year {year}. "
            "Cannot compute CNS18-20 fractions."
        )
        raise RuntimeError(msg)

    return {
        "edu_frac": result["govt_edu"] / total,
        "med_frac": result["govt_med"] / total,
        "pub_frac": result["govt_pub"] / total,
    }


def _compute_cns18_20_fractions(
    cbp_totals: dict[str, float],
    state_fips: str,
    county_fips: str,
    lodes_cns10: float = 0.0,
    lodes_cns11: float = 0.0,
    lodes_cns15: float = 0.0,
) -> dict[str, float]:
    """Compute CNS18-20 distribution fractions.

    Distributes government sector employment (CNS18 Federal, CNS19 State,
    CNS20 Local) across education, medical, and public_admin sub-sectors
    using QCEW (Quarterly Census of Employment and Wages) government
    employment data.

    Downloads BLS QCEW data for the given county, filters for government-owned
    establishments (own_code 1/2/3) in education (NAICS 61), health (NAICS 62),
    and public administration (NAICS 92), and returns employment fractions
    proportional to each sub-sector's share of government employment.

    Args:
        cbp_totals: Ignored (kept for backward compat with callers).
        state_fips: Two-digit state FIPS code (used for QCEW fetch).
        county_fips: Three-digit county FIPS code (used for QCEW fetch).
        lodes_cns10: Ignored (kept for backward compat with callers).
        lodes_cns11: Ignored (kept for backward compat with callers).
        lodes_cns15: Ignored (kept for backward compat with callers).

    Returns:
        Dict with keys ``cns18_20_edu_frac``, ``cns18_20_med_frac``,
        ``cns18_20_pub_frac`` summing to 1.0.

    Raises:
        RuntimeError: If QCEW data cannot be fetched (network error,
            empty data, or zero total government employment).
    """
    qcew_fracs = _fetch_qcew_government_split(state_fips, county_fips)
    return {
        "cns18_20_edu_frac": qcew_fracs["edu_frac"],
        "cns18_20_med_frac": qcew_fracs["med_frac"],
        "cns18_20_pub_frac": qcew_fracs["pub_frac"],
    }


def _populate_wac_block(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
    force_reload: bool = False,
) -> int:
    """Join LEHD LODES WAC data with TIGER BG geometry via a two-step dbt pipeline.

    1. ``wac_block_raw`` — CNS-to-sub-sector splitting with CBP proportions.
    2. ``wac_block`` — C000 gap distribution and CBP county-level scaling
       to correct LEHD disclosure suppression.


    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: LEHD data year (default 2021).
        force_reload: If True, restate the models even if unchanged.

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If dbt fails or the table is empty.
    """
    cbp_props = _build_cbp_proportions(state_fips, county_fips, year)
    # Validate CBP proportions: parent-group totals must be non-zero.
    # All-zero proportions mean the CBP API returned no usable data and
    # no fallback was generated — this is a data dependency failure.
    cns01_sum = (
        cbp_props.get("11", 0.0) + cbp_props.get("21", 0.0) + cbp_props.get("23", 0.0)
    )
    cns03_sum = (
        cbp_props.get("22", 0.0)
        + cbp_props.get("42", 0.0)
        + cbp_props.get("44", 0.0)
        + cbp_props.get("45", 0.0)
        + cbp_props.get("48", 0.0)
        + cbp_props.get("49", 0.0)
    )
    if cns01_sum <= 0 or cns03_sum <= 0:
        raise RuntimeError(
            f"CBP proportions unavailable for {state_fips}/{county_fips} year {year}: "
            f"CNS01 sum={cns01_sum:.3f} CNS03 sum={cns03_sum:.3f}. "
            "The Census CBP API returned no usable employment data. "
            "Ensure CENSUS_API_KEY is set and the requested year is available."
        )

    # Build dbt vars for wac_block_raw (CNS splitting + SACOG calibration).
    raw_vars: dict[str, object] = {
        "state_fips": state_fips,
        "county_fips": county_fips,
        "lodes_year": year,
        "cbp_11": cbp_props.get("11", 0.0),
        "cbp_21": cbp_props.get("21", 0.0),
        "cbp_48": cbp_props.get("48", 0.0),
        "cbp_49": cbp_props.get("49", 0.0),
        "cbp_22": cbp_props.get("22", 0.0),
        "cbp_42": cbp_props.get("42", 0.0),
        "cbp_721": cbp_props.get("721", 0.0),
        "tiger_block_vintage": "2020",
        "tiger_bg_vintage": "2023",
    }

    # Step 1: Fetch CBP county totals and compute CNS18-20 fractions
    cbp_totals = _compute_all_cbp_totals(state_fips, county_fips, year=year)

    cns18_20_fracs = _compute_cns18_20_fractions(
        cbp_totals,
        state_fips=state_fips,
        county_fips=county_fips,
    )
    raw_vars.update(cns18_20_fracs)

    # Step 2: CNS split → lehd.wac_block_raw (now with CNS18-20 fractions)
    # Build dbt vars for wac_block (CBP county scaling).
    scaling_vars: dict[str, object] = {
        "cbp_preserve_fraction": 0.50,
    }
    for sub_col in _SUBSECTOR_CBP_NAICS:
        cbp_key = f"cbp_county_{sub_col}"
        scaling_vars[cbp_key] = cbp_totals.get(sub_col, 0.0)

    # Materialize wac_block_raw (CNS-to-sub-sector splitting with CBP proportions)
    def _restate_list() -> list[str]:
        from brewgis.workspace.analysis.sqlmesh_runner import get_context

        ctx = get_context()
        existing = ["brewgis.staging.wac_block_raw", "brewgis.staging.wac_block"]
        return [m for m in existing if m in ctx.models]

    restate_wac = _restate_list() if force_reload else False
    run_sqlmesh_plan(
        environment="brewgis_prod",
        select=["brewgis.staging.wac_block_raw"],
        skip_tests=True,
        variables=raw_vars,
        restate_models=restate_wac,
    )

    # Materialize wac_block (C000 gap distribution and CBP county-level scaling)
    run_sqlmesh_plan(
        environment="brewgis_prod",
        select=["brewgis.staging.wac_block"],
        skip_tests=True,
        variables=scaling_vars,
        restate_models=restate_wac,
    )

    engine = get_engine()
    with engine.connect() as conn:
        row_count = (
            conn.execute(
                text("SELECT COUNT(*) FROM staging__brewgis_prod.wac_block")
            ).scalar()
            or 0
        )

    if row_count == 0:
        msg = (
            f"No LEHD WAC block data returned for "
            f"{state_fips}/{county_fips} year {year}"
        )
        raise RuntimeError(msg)
    return row_count
