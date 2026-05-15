"""LEHD → LODES employment data fetcher with CBP-based sub-sector splitting.

Downloads LODES (Longitudinal Employer-Household Dynamics) Workplace Area
Characteristics (WAC) data from the CES FTP server, and County Business
Patterns (CBP) data from the Census API for detailed sub-sector proportional
splitting.

Data available: 2002-2021.
See https://lehd.ces.census.gov/data/lodes/LODES7/ for documentation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import deal
import geopandas as gpd
import pandas as pd
import requests
from shapely import wkt as geom

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)


def _census_api_key() -> str:
    """Return Census API key from Django settings, or empty string."""
    try:
        from django.conf import settings as django_settings

        return django_settings.CENSUS_API_KEY or ""
    except Exception:
        return ""


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

    key = _census_api_key()
    key_param = f"&key={key}" if key else ""
    url = (
        f"https://api.census.gov/data/{year}/cbp"
        f"?get=EMP,NAICS2017&for=county:{county_fips_clean}"
        f"&in=state:{state_fips_clean}{key_param}"
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


# ── CBP County-Scale Calibration ──────────────────────────────────────


# NAICS 2-digit codes per broad employment sector for county-level scaling.
# These mirror the AGGREGATE_MAPPINGS groupings.
_SECTOR_NAICS: dict[str, list[str]] = {
    "emp_ret": ["44", "45"],
    "emp_off": ["51", "52", "53", "54", "55", "56", "62"],
    "emp_pub": ["61", "92"],
    "emp_ind": ["11", "21", "22", "23", "31", "32", "33", "42", "48", "49"],
}


def _cbp_url(state_fips: str, county_fips: str, naics_code: str) -> str:
    """Build CBP API URL for a single 2-digit NAICS code in a county.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        naics_code: Two-digit NAICS code.

    Returns:
        Census CBP API URL string.
    """
    sf = state_fips.zfill(2)
    cf = county_fips.zfill(3)
    key = _census_api_key()
    key_param = f"&key={key}" if key else ""
    return (
        f"https://api.census.gov/data/2021/cbp"
        f"?get=EMP,NAICS2017&for=county:{cf}"
        f"&in=state:{sf}&NAICS2017={naics_code}----{key_param}"
    )


def _fetch_cbp_county_emp(
    state_fips: str,
    county_fips: str,
    naics_codes: dict[str, str],
) -> dict[str, float]:
    """Fetch CBP employment for specified 2-digit NAICS codes.

    Queries the Census CBP API for each NAICS code individually and
    returns a dict mapping each key to its employment count (0.0 if
    the code has no data or the API call fails).

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        naics_codes: Dict mapping a key name to a 2-digit NAICS code.

    Returns:
        Dict mapping each input key to its CBP employment (float).
    """
    result: dict[str, float] = {}
    for key, naics_code in naics_codes.items():
        url = _cbp_url(state_fips, county_fips, naics_code)
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        raw_data: list[list[str]] = response.json()
        if len(raw_data) >= 2:  # at least header + one data row
            emp_raw = raw_data[1][0]  # EMP is the first column
            if emp_raw not in ("", "D", "S", "N"):
                result[key] = float(emp_raw)
            else:
                result[key] = 0.0
        else:
            result[key] = 0.0
    return result


def fetch_county_employment_scaling(
    state_fips: str,
    county_fips: str,
) -> dict[str, float]:
    """Compute CBP-based county-level employment scaling factors.

    Fetches LEHD block employment data and CBP county totals for each
    broad sector (retail, office, public, industrial) and returns
    scaling factors that only scale up (never down) where CBP reports
    more employment than LEHD captures.

    Scaling factor per sector = max(CBP_total / LEHD_total, 1.0).

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        Dict with keys ``emp_ret``, ``emp_off``, ``emp_pub``, ``emp_ind``
        mapped to float scaling factors (default 1.0).
    """
    scale_factors: dict[str, float] = {
        "emp_ret": 1.0,
        "emp_off": 1.0,
        "emp_pub": 1.0,
        "emp_ind": 1.0,
    }

    # 1. Compute LEHD county-level totals per sector
    lehd_gdf = fetch_lehd_block_data(state_fips, county_fips)

    if lehd_gdf.empty:
        return scale_factors

    lehd_totals: dict[str, float] = {}
    for sector in _SECTOR_NAICS:
        lehd_totals[sector] = (
            float(lehd_gdf[sector].sum()) if sector in lehd_gdf.columns else 0.0
        )

    # 2. Fetch CBP county totals per NAICS 2-digit code
    flat_naics: dict[str, str] = {}
    for sector, codes in _SECTOR_NAICS.items():
        for naics_code in codes:
            flat_naics[f"{sector}_{naics_code}"] = naics_code

    cbp_results = _fetch_cbp_county_emp(state_fips, county_fips, flat_naics)

    # 3. Aggregate CBP per sector
    sector_cbp: dict[str, float] = dict.fromkeys(_SECTOR_NAICS, 0.0)
    for flat_key, emp in cbp_results.items():
        for sector in _SECTOR_NAICS:
            if flat_key.startswith(f"{sector}_"):
                sector_cbp[sector] += emp
                break

    # 4. Compute scaling factor = max(CBP / LEHD, 1.0)
    for sector in scale_factors:
        lehd_total = lehd_totals.get(sector, 0.0)
        cbp_total = sector_cbp.get(sector, 0.0)
        if lehd_total > 0 and cbp_total > 0:
            ratio = cbp_total / lehd_total
            if ratio > 1.0:
                scale_factors[sector] = ratio
            # else keep 1.0 (never scale down)
        # else keep 1.0 (no data or zero LEHD)

    return scale_factors


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
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"year": year})
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
        row_count = result if result else 0
    return {
        "row_count": row_count,
        "variables": list(LODES_WAC_VARIABLES.keys()),
        "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
        "sub_sector_count": len(_NAICS_SPLIT_RULES),
    }


def fetch_lehd_block_polygons(
    state_fips: str,
    county_fips: str,
    use_cache: bool = True,
) -> gpd.GeoDataFrame:
    """Fetch LODES employment data with real block polygon geometry.

    Reads LODES attributes from the lodes_raw staging table and joins
    with polygon geometry from the tiger_blocks staging table.

    Falls back to data without geometry if tiger_blocks data is unavailable.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        use_cache: Kept for backward compatibility (unused).

    Returns:
        GeoDataFrame with polygon geometry, ``geoid``, and all
        employment columns mapped to BaseCanvasSchema names.
    """
    # 1. Fetch LODES attribute data (now from staging)
    lehd_gdf = fetch_lehd_block_data(state_fips, county_fips)
    county_geoid_prefix = state_fips.zfill(2) + county_fips.zfill(3)
    lehd_gdf = lehd_gdf[lehd_gdf["geoid"].str.startswith(county_geoid_prefix)].copy()

    if lehd_gdf.empty:
        raise RuntimeError(f"No LODES blocks match county FIPS {county_fips}")

    # 2. Read TIGER block geometry from staging
    engine = get_engine()
    geo_query = text("""
        SELECT geoid, geometry FROM public.tiger_block_groups
        WHERE state_fips = :state_fips
    """)
    with engine.connect() as conn:
        result = conn.execute(geo_query, {"state_fips": state_fips})
        geo_rows = result.fetchall()
        geo_columns = list(result.keys())

    # Build geoid to geometry map
    geo_map = {}
    for row in geo_rows:
        row_dict = dict(zip(geo_columns, row, strict=False))
        wkt_geom = row_dict.get("geometry")
        if wkt_geom:
            geo_map[row_dict["geoid"]] = geom.loads(str(wkt_geom))

    # 3. Join attributes to geometry
    # LODES w_geocode is 15-digit block GEOID (SS CC TTTTTT BBBB).
    # TIGER block_groups has 12-digit GEOID (SS CC TTTTTT B).
    # Truncate to match at block-group level.
    lehd_gdf["bg_geoid"] = lehd_gdf["geoid"].str[:12]
    lehd_attrs = lehd_gdf.drop(columns=["geometry"], errors="ignore")
    lehd_gdf["geometry"] = lehd_gdf["bg_geoid"].map(geo_map)
    # Filter out rows without geometry
    filtered = lehd_gdf[~lehd_gdf.geometry.isna()].copy()
    # Explicitly construct GeoDataFrame with geometry and CRS
    if not filtered.empty:
        result = gpd.GeoDataFrame(filtered, geometry="geometry", crs="EPSG:4326")
        return result
    raise RuntimeError(
        f"LODES data did not match TIGER blocks for {state_fips}/{county_fips}"
    )


def _populate_wac_block(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> int:
    """Fetch LEHD LODES WAC data, join with TIGER BG geometry, and write to ``lehd.wac_block``.

    The pipeline's ``_allocate_employment`` step reads from
    ``lehd.wac_block``.  This helper creates it by running the
    existing ``fetch_lehd_block_polygons`` query and persisting the
    result as a PostGIS table.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: LEHD data year (default 2021).

    Returns:
        Number of rows written.

    Raises:
        RuntimeError: If the query returns no data.
    """
    gdf = fetch_lehd_block_polygons(state_fips, county_fips)

    if gdf.empty:
        raise RuntimeError(
            f"No LEHD WAC block data returned for {state_fips}/{county_fips} year {year}"
        )

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS lehd"))
        conn.commit()

    gdf.to_postgis(
        "wac_block",
        engine,
        schema="lehd",
        if_exists="replace",
        index=False,
        dtype={"geometry": "geometry(MultiPolygon, 4326)"},
    )

    return len(gdf)
