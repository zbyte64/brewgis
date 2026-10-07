"""LEHD → LODES employment data — the report vocabulary the preview renders.

The LODES fetch itself is a SQLMesh model: ``duckdb.<region>.lodes_raw`` reads
the gzipped WAC CSV from the CES FTP through httpfs and
``brewgis.<region>.wac_block_raw`` maps CNS sectors to base-canvas sub-sectors on
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
# CNS01-CNS20 (the 20 two-digit NAICS sectors per block, LODES8 tech doc)

LODES_WAC_VARIABLES: dict[str, str] = {
    "C000": "emp",
    "CNS01": "cns_agriculture",  # NAICS 11
    "CNS02": "cns_mining",  # NAICS 21
    "CNS03": "cns_utilities",  # NAICS 22
    "CNS04": "cns_construction",  # NAICS 23
    "CNS05": "cns_manufacturing",  # NAICS 31-33
    "CNS06": "cns_wholesale",  # NAICS 42
    "CNS07": "cns_retail",  # NAICS 44-45
    "CNS08": "cns_transportation_warehousing",  # NAICS 48-49
    "CNS09": "cns_information",  # NAICS 51
    "CNS10": "cns_finance_insurance",  # NAICS 52
    "CNS11": "cns_real_estate",  # NAICS 53
    "CNS12": "cns_professional_services",  # NAICS 54
    "CNS13": "cns_management",  # NAICS 55
    "CNS14": "cns_admin_support",  # NAICS 56
    "CNS15": "cns_educational_services",  # NAICS 61
    "CNS16": "cns_health_care",  # NAICS 62
    "CNS17": "cns_arts_entertainment",  # NAICS 71
    "CNS18": "cns_accommodation_food",  # NAICS 72
    "CNS19": "cns_other_services",  # NAICS 81
    "CNS20": "cns_public_administration",  # NAICS 92
}

# ── CNS → Base-Canvas Sub-Sector Rules ────────────────────────────────
#
# Each key is a LODES CNS column name. The value is a list of (target_sub_sector, source_spec)
# tuples where source_spec is:
#   * A string (NAICS regex pattern) — proportion is derived from CBP employment
#   * A float — fixed fraction of the CNS total
#   * None — takes the remainder after all previous non-None entries in the list
#
# Only CNS18 (NAICS 72) is split, by the CBP NAICS 721 share of NAICS 72.
# LODES has no military segment, so emp_military has no source.

_NAICS_SPLIT_RULES: dict[str, list[tuple[str, str | float | None]]] = {
    "CNS01": [("emp_agriculture", 1.0)],
    "CNS02": [("emp_extraction", 1.0)],
    "CNS03": [("emp_utilities", 1.0)],
    "CNS04": [("emp_construction", 1.0)],
    "CNS05": [("emp_manufacturing", 1.0)],
    "CNS06": [("emp_wholesale", 1.0)],
    "CNS07": [("emp_retail_services", 1.0)],
    "CNS08": [("emp_transport_warehousing", 1.0)],
    # CNS09-14 (NAICS 51-56) → office services
    "CNS09": [("emp_office_services", 1.0)],
    "CNS10": [("emp_office_services", 1.0)],
    "CNS11": [("emp_office_services", 1.0)],
    "CNS12": [("emp_office_services", 1.0)],
    "CNS13": [("emp_office_services", 1.0)],
    "CNS14": [("emp_office_services", 1.0)],
    "CNS15": [("emp_education", 1.0)],
    "CNS16": [("emp_medical_services", 1.0)],
    "CNS17": [("emp_arts_entertainment", 1.0)],
    "CNS18": [
        ("emp_accommodation", r"^721\s*-*"),
        ("emp_restaurant", None),  # remainder (722)
    ],
    "CNS19": [("emp_other_services", 1.0)],
    "CNS20": [("emp_public_admin", 1.0)],
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
