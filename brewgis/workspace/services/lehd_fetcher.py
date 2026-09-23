"""LEHD → LODES employment data — the report vocabulary the preview renders.

The LODES fetch itself is a SQLMesh model: ``duckdb.<region>.lodes_raw`` reads
the gzipped WAC CSV from the CES FTP through httpfs and
``brewgis.<region>.wac_block_raw`` splits CNS sectors into NAICS sub-sectors on
the way into PostGIS. Django's part is the import form, the plan, and the copy
into the workspace schema (see ``tasks.run_lehd_fetch``); what remains here are
the WAC variable names, the sub-sector split rules, and the aggregate-column
mappings the import preview reports.

Data available: 2002-2021.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.analysis.sqlmesh_runner import get_context

logger = logging.getLogger(__name__)


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


def fetch_lehd_data_summary(
    state_fips: str,
    county_fips: str,
    year: int = 2021,
) -> dict[str, Any]:
    """Return a summary of available employment data from staging."""
    context = get_context()
    df = context.fetchdf("""
        SELECT COUNT(*) as row_count
        FROM brewgis.sacog.lodes_raw
        WHERE year = :year
    """)
    row_count = df[0][0] or 0
    return {
        "row_count": row_count,
        "variables": list(LODES_WAC_VARIABLES.keys()),
        "aggregate_columns": list(AGGREGATE_MAPPINGS.keys()),
        "sub_sector_count": len(_NAICS_SPLIT_RULES),
    }
