"""dlt pipeline for Census ACS 5-year raw data extraction.

Replaces the raw API download portion of census_fetcher. Writes raw
Census JSON (column-name-keyed dicts per block group) to a Postgres
staging table. Domain-specific post-processing (geometry, column
mapping, NAICS splitting) stays in the existing fetcher modules.
"""

from __future__ import annotations

__all__ = ["run_census_pipeline"]

import dlt
import requests

from brewgis.workspace.services.census_fetcher import _all_vars
from brewgis.workspace.services.census_fetcher import _census_api_key
from brewgis.workspace.services.census_fetcher import _census_base_url


@dlt.resource(name="acs_raw", write_disposition="replace")
def census_acs_resource(state_fips, county_fips, year=2022):  # noqa: ANN001, ANN202
    """Fetch raw ACS data from Census API, yielding one dict per block group.

    No type annotations on parameters — dlt uses inspect and type hints
    conflict with its runtime signature introspection.
    """
    vars_ = _all_vars()
    vars_str = ",".join(vars_)
    base = _census_base_url(year)
    url = (
        f"{base}?get={vars_str}"
        f"&in=state:{state_fips}"
        f"&in=county:{county_fips}"
        f"&for=block%20group:*"
    )
    api_key = _census_api_key()
    if api_key:
        url += f"&key={api_key}"

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    data = response.json()
    # Census returns [["header1","header2"],[val1,val2],...]
    headers = data[0]
    for row in data[1:]:
        yield dict(zip(headers, row, strict=False))


def run_census_pipeline(
    state_fips: str,
    county_fips: str,
    year: int = 2022,
    schema: str = "public",
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
        ``{"success": True, "table_name": str, "row_count": int, "load_info": str}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"census_acs_{state_fips}_{county_fips}_{year}",
        destination="postgres",
        dataset_name=schema,
    )

    try:
        load_info = pipeline.run(census_acs_resource(state_fips, county_fips, year))

        stats = load_info.load_packages[0].job_metrics
        metrics = stats.get("acs_raw", [])
        row_count = sum(m.total_rows for m in metrics if hasattr(m, "total_rows"))

        return {
            "success": True,
            "table_name": f"{schema}.acs_raw",
            "row_count": row_count,
            "load_info": str(load_info),
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
