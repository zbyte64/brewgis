"""dlt pipeline for Census ACS 5-year raw data extraction.

Writes raw Census JSON (column-name-keyed dicts per block group) to a
PostgreSQL staging table via dlt. Supports incremental loading based on
the ACS year so that re-runs only fetch new survey years.

Domain-specific post-processing (geometry, column mapping, NAICS
splitting) stays in :mod:`brewgis.workspace.services.census_fetcher`.
"""

from __future__ import annotations

import json
import logging

__all__ = [
    "census_source",
    "run_census_pipeline",
]

from pathlib import Path
from typing import Any

import dlt
import requests
from django.conf import settings

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.services.census_fetcher import _all_vars
from brewgis.workspace.services.census_fetcher import _census_api_key
from brewgis.workspace.services.census_fetcher import _census_base_url

logger = logging.getLogger(__name__)

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

_SENTINELS = frozenset({"-666666666", "-555555555", "-333333333"})


@dlt.source(name="census_acs", max_table_nesting=0)
def census_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: int | dlt.sources.incremental[int] = dlt.sources.incremental[int]("year"),
    ignore_cache: bool = False,
) -> list[Any]:
    """dlt source for Census ACS 5-year data extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: Incremental year — tracks the maximum year already loaded
            and only fetches new years on re-run.

    Returns:
        List with a single :class:`dlt.Resource` yielding block-group-level
        dicts keyed by Census variable name.
    """
    return [census_acs_resource(state_fips, county_fips, year, ignore_cache)]


@dlt.resource(
    name="acs_raw",
    write_disposition="replace",
    primary_key=("year", "state", "county", "tract", "block group"),
    columns={
        "year": {"data_type": "bigint", "nullable": False},
        "b01001_001_e": {"data_type": "bigint", "nullable": True},
        "b25003_001_e": {"data_type": "bigint", "nullable": True},
        "b25003_002_e": {"data_type": "bigint", "nullable": True},
        "b25003_003_e": {"data_type": "bigint", "nullable": True},
        "b25024_001_e": {"data_type": "bigint", "nullable": True},
        "b25024_002_e": {"data_type": "bigint", "nullable": True},
        "b25024_003_e": {"data_type": "bigint", "nullable": True},
        "b25024_004_e": {"data_type": "bigint", "nullable": True},
        "b25024_005_e": {"data_type": "bigint", "nullable": True},
        "b25024_006_e": {"data_type": "bigint", "nullable": True},
        "b25024_007_e": {"data_type": "bigint", "nullable": True},
        "b25024_008_e": {"data_type": "bigint", "nullable": True},
        "b25024_009_e": {"data_type": "bigint", "nullable": True},
        "b25008_001_e": {"data_type": "bigint", "nullable": True},
        "b25008_002_e": {"data_type": "bigint", "nullable": True},
        "b25008_003_e": {"data_type": "bigint", "nullable": True},
        "b19013_001_e": {"data_type": "bigint", "nullable": True},
        "b25070_001_e": {"data_type": "bigint", "nullable": True},
        "b25070_007_e": {"data_type": "bigint", "nullable": True},
        "b25070_008_e": {"data_type": "bigint", "nullable": True},
        "b25070_009_e": {"data_type": "bigint", "nullable": True},
        "b25070_010_e": {"data_type": "bigint", "nullable": True},
        "b25091_001_e": {"data_type": "bigint", "nullable": True},
        "b25091_005_e": {"data_type": "bigint", "nullable": True},
        "b25091_006_e": {"data_type": "bigint", "nullable": True},
        "b25091_007_e": {"data_type": "bigint", "nullable": True},
        "b25091_011_e": {"data_type": "bigint", "nullable": True},
        "b25091_012_e": {"data_type": "bigint", "nullable": True},
        "b25091_013_e": {"data_type": "bigint", "nullable": True},
        "b03002_001_e": {"data_type": "bigint", "nullable": True},
        "b03002_002_e": {"data_type": "bigint", "nullable": True},
        "b03002_003_e": {"data_type": "bigint", "nullable": True},
        "b03002_004_e": {"data_type": "bigint", "nullable": True},
        "b03002_005_e": {"data_type": "bigint", "nullable": True},
        "b03002_012_e": {"data_type": "bigint", "nullable": True},
        "b15003_001_e": {"data_type": "bigint", "nullable": True},
        "b15003_022_e": {"data_type": "bigint", "nullable": True},
        "b15003_023_e": {"data_type": "bigint", "nullable": True},
        "b15003_024_e": {"data_type": "bigint", "nullable": True},
        "b15003_025_e": {"data_type": "bigint", "nullable": True},
    },
)
def census_acs_resource(
    state_fips: str,
    county_fips: str,
    year: int | dlt.sources.incremental[int] = dlt.sources.incremental[int]("year"),
    ignore_cache: bool = False,
) -> Any:
    """Yield raw ACS data from Census API, one dict per block group.

    dlt's incremental tracking ensures that already-loaded years are
    skipped on subsequent runs. The ``year`` field is the merge key.
    """
    year_val: int = (
        year.last_value if isinstance(year, dlt.sources.incremental) else year
    )
    dl_path = (
        CACHE_DIR
        / "census_acs_resource"
        / str(year_val)
        / state_fips
        / f"{county_fips}.json"
    )
    dl_path.parent.mkdir(exist_ok=True, parents=True)

    # Try loading from cache first
    data: Any = None
    if not ignore_cache and dl_path.exists():
        with dl_path.open() as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(
                "Cached ACS data is %s instead of list, re-downloading",
                type(data).__name__,
            )
            data = None

    if data is None:
        vars_ = _all_vars()
        vars_str = ",".join(vars_)
        base = _census_base_url(year_val)
        url = (
            f"{base}?get={vars_str}"
            f"&for=block+group:*"
            f"&in=state:{state_fips}+county:{county_fips}+tract:*"
        )
        api_key = _census_api_key()
        if api_key:
            url += f"&key={api_key}"

        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            logger.error(
                "Census ACS API returned %s instead of list. URL: %s, Body: %s",
                type(data).__name__,
                url,
                response.text[:500],
            )
            raise RuntimeError(
                f"Census ACS API returned {type(data).__name__} instead of list. "
                f"URL: {url}, Body: {response.text[:500]}"
            )
        with dl_path.open("w") as f:
            json.dump(data, f)

    headers = data[0]
    for row in data[1:]:
        record = dict(zip(headers, row, strict=False))
        record["year"] = year_val
        for k, v in record.items():
            if v in _SENTINELS:
                record[k] = None
        yield record


def run_census_pipeline(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
    schema: str = "public",
    ignore_cache: bool = False,
    **kwargs: Any,
) -> dict:
    """Run dlt pipeline to extract raw Census ACS data to a staging table.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    county_fips : str
        Three-digit county FIPS code.
    year : int, optional
        ACS 5-year data year (default 2022).
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
        pipeline_name=f"census_acs_{state_fips}_{county_fips}_{year}",
        destination="postgres",
        dataset_name=schema,
        **kwargs,
    )

    load_info = pipeline.run(
        census_source(state_fips, county_fips, year, ignore_cache=ignore_cache),
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("acs_raw", 0)
            break

    # Create index for acs_block_group lookups
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_acs_raw_lookup "
                f"ON {schema}.acs_raw (state, county, year)"
            )
        )

    return {
        "table_name": f"{schema}.acs_raw",
        "row_count": row_count,
        "load_info": str(load_info),
    }
