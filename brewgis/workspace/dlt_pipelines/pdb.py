"""dlt pipeline for Census Planning Database (PDB) extraction.

Extracts block-group-level PDB data (vacancy rates, group quarters
population, low response score, tenure, poverty) from the Census PDB API
and writes to a PostgreSQL staging table via dlt. Uses replace disposition
since the PDB is a point-in-time dataset.
"""

from __future__ import annotations

import json
import logging

__all__ = [
    "pdb_source",
    "run_pdb_pipeline",
]

from pathlib import Path
from typing import Any

import dlt
import requests
from django.conf import settings

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

_SENTINELS = frozenset({"-666666666", "-555555555", "-333333333"})

_BASE_URL = "https://api.census.gov/data/2024/pdb/blockgroup"

# PDB variables to extract
_PDB_VARS = [
    "GIDBG",
    "Tot_Vacant_Units_ACS_18_22",
    "Tot_Housing_Units_ACS_18_22",
    "Tot_Occp_Units_ACS_18_22",
    "Tot_GQ_CEN_2020",
    "Inst_GQ_CEN_2020",
    "Non_Inst_GQ_CEN_2020",
    "Low_Response_Score",
    "pct_Renter_Occp_HU_ACS_18_22",
    "pct_Prs_Blw_Pov_Lev_ACS_18_22",
    "Tot_Population_ACS_18_22",
]


@dlt.source(name="census_pdb", max_table_nesting=0)
def pdb_source(
    state_fips: str = "06",
    county_fips: str = "067",
    ignore_cache: bool = False,
) -> list[Any]:
    """dlt source for Census Planning Database block group extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.

    Returns:
        List with a single :class:`dlt.Resource` yielding block-group-level
        dicts keyed by PDB variable name.
    """
    return [census_pdb_resource(state_fips, county_fips, ignore_cache)]


@dlt.resource(
    name="pdb_raw",
    write_disposition="replace",
    primary_key=("gidbg", "state", "county"),
    columns={
        "gidbg": {"data_type": "text", "nullable": False},
        "tot_vacant_units_acs_18_22": {"data_type": "bigint", "nullable": True},
        "tot_housing_units_acs_18_22": {"data_type": "bigint", "nullable": True},
        "tot_occp_units_acs_18_22": {"data_type": "bigint", "nullable": True},
        "tot_gq_cen_2020": {"data_type": "bigint", "nullable": True},
        "inst_gq_cen_2020": {"data_type": "bigint", "nullable": True},
        "non_inst_gq_cen_2020": {"data_type": "bigint", "nullable": True},
        "low_response_score": {"data_type": "double", "nullable": True},
        "pct_renter_occp_hu_acs_18_22": {"data_type": "double", "nullable": True},
        "pct_prs_blw_pov_lev_acs_18_22": {"data_type": "double", "nullable": True},
        "tot_population_acs_18_22": {"data_type": "bigint", "nullable": True},
        "state": {"data_type": "text", "nullable": False},
        "county": {"data_type": "text", "nullable": False},
        "data_year": {"data_type": "bigint", "nullable": False},
    },
)
def census_pdb_resource(
    state_fips: str,
    county_fips: str,
    ignore_cache: bool = False,
) -> Any:
    """Yield raw PDB data from Census API, one dict per block group.

    Uses replace write disposition since the PDB is a point-in-time
    dataset (ACS 2018-2022 vintage) and there is no incremental key.
    """
    dl_path = CACHE_DIR / "census_pdb_resource" / state_fips / f"{county_fips}.json"
    dl_path.parent.mkdir(exist_ok=True, parents=True)

    # Try loading from cache first
    data: Any = None
    if not ignore_cache and dl_path.exists():
        with dl_path.open() as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(
                "Cached PDB data is %s instead of list, re-downloading",
                type(data).__name__,
            )
            data = None

    if data is None:
        vars_str = ",".join(_PDB_VARS)
        url = (
            f"{_BASE_URL}?get={vars_str}"
            f"&for=block+group:*"
            f"&in=state:{state_fips}+county:{county_fips}"
        )
        api_key = settings.CENSUS_API_KEY
        if api_key:
            url += f"&key={api_key}"

        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(
                f"Census PDB API returned {type(data).__name__} instead of list. "
                f"Status: {response.status_code}, URL: {response.url}, "
                f"Body: {response.text[:500]}"
            )
        with dl_path.open("w") as f:
            json.dump(data, f)

    headers = data[0]
    for row in data[1:]:
        record: dict[str, Any] = dict(zip(headers, row, strict=False))

        # Map original uppercase PDB column names to lowercase schema columns,
        # including GIDBG which is renamed to gidbg.
        col_map = {
            "GIDBG": "gidbg",
            "Tot_Vacant_Units_ACS_18_22": "tot_vacant_units_acs_18_22",
            "Tot_Housing_Units_ACS_18_22": "tot_housing_units_acs_18_22",
            "Tot_Occp_Units_ACS_18_22": "tot_occp_units_acs_18_22",
            "Tot_GQ_CEN_2020": "tot_gq_cen_2020",
            "Inst_GQ_CEN_2020": "inst_gq_cen_2020",
            "Non_Inst_GQ_CEN_2020": "non_inst_gq_cen_2020",
            "Low_Response_Score": "low_response_score",
            "pct_Renter_Occp_HU_ACS_18_22": "pct_renter_occp_hu_acs_18_22",
            "pct_Prs_Blw_Pov_Lev_ACS_18_22": "pct_prs_blw_pov_lev_acs_18_22",
            "Tot_Population_ACS_18_22": "tot_population_acs_18_22",
        }
        for old_key, new_key in col_map.items():
            if old_key in record:
                record[new_key] = record.pop(old_key)

        record["state"] = state_fips
        record["county"] = county_fips
        record["data_year"] = 2024

        # Convert numeric fields and handle sentinels
        _numeric_fields = {
            "tot_vacant_units_acs_18_22",
            "tot_housing_units_acs_18_22",
            "tot_occp_units_acs_18_22",
            "tot_gq_cen_2020",
            "inst_gq_cen_2020",
            "non_inst_gq_cen_2020",
            "low_response_score",
            "pct_renter_occp_hu_acs_18_22",
            "pct_prs_blw_pov_lev_acs_18_22",
            "tot_population_acs_18_22",
        }
        for k, v in record.items():
            if isinstance(v, str) and v in _SENTINELS:
                record[k] = None
            elif k in _numeric_fields and v is not None and isinstance(v, str):
                try:
                    record[k] = float(v) if "." in v else int(v)
                except (ValueError, TypeError):
                    record[k] = None

        yield record


def run_pdb_pipeline(
    state_fips: str,
    county_fips: str,
    schema: str = "public",
    ignore_cache: bool = False,
    **kwargs: Any,
) -> dict:
    """Run dlt pipeline to extract raw PDB data to a staging table.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    county_fips : str
        Three-digit county FIPS code.
    schema : str, optional
        Postgres schema for the staging table (default "public").

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int,
        "load_info": str}`` on success, or ``{"success": False,
        "error": str}`` on failure.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"census_pdb_{state_fips}_{county_fips}",
        destination="postgres",
        dataset_name=schema,
        **kwargs,
    )

    load_info = pipeline.run(
        pdb_source(state_fips, county_fips, ignore_cache=ignore_cache),
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("pdb_raw", 0)
            break

    # Create index for pdb_block_group lookups
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_pdb_raw_lookup "
                f"ON {schema}.pdb_raw (state, county)"
            )
        )

    return {
        "table_name": f"{schema}.pdb_raw",
        "row_count": row_count,
        "load_info": str(load_info),
    }
