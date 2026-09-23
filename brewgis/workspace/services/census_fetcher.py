"""Census ACS demographics — the ACS table groups the import reports on.

The ACS fetch itself is a SQLMesh model: ``duckdb.census.acs_raw`` reads the
Census API through httpfs and ``brewgis.<region>.acs_block_group`` bridges the
derived demographics into PostGIS. Django's part is the import form, the plan,
and the copy into the workspace schema (see ``tasks.run_census_fetch``); what
remains here is the table-group description the import preview renders and the
staging counts it reports.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)


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
        FROM brewgis.sacog.acs_bridge
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
