"""dlt pipeline for Census ACS 5-year raw data extraction.

Writes raw Census JSON (column-name-keyed dicts per block group) to a
PostgreSQL staging table via dlt. Supports incremental loading based on
the ACS year so that re-runs only fetch new survey years.

Domain-specific post-processing (geometry, column mapping, NAICS
splitting) stays in :mod:`brewgis.workspace.services.census_fetcher`.
"""

from __future__ import annotations

__all__ = [
    "census_source",
    "run_census_pipeline",
]

from typing import Any
import dlt
import requests

from brewgis.workspace.services.census_fetcher import _all_vars
from brewgis.workspace.services.census_fetcher import _census_api_key
from brewgis.workspace.services.census_fetcher import _census_base_url


@dlt.source(name="census_acs", max_table_nesting=0)
def census_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: int = dlt.sources.incremental[int]("year"),  # type: ignore[assignment]
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
    return [census_acs_resource(state_fips, county_fips, year)]


@dlt.resource(
    name="acs_raw",
    write_disposition="merge",
    primary_key="year",
    columns={
        "year": {"data_type": "bigint", "nullable": False},
    },
)
def census_acs_resource(
    state_fips: str,
    county_fips: str,
    year: int = dlt.sources.incremental[int]("year"),  # type: ignore[assignment]
) -> Any:
    """Yield raw ACS data from Census API, one dict per block group.

    dlt's incremental tracking ensures that already-loaded years are
    skipped on subsequent runs. The ``year`` field is the merge key.
    """
    year_val: int = year.last_value if isinstance(year, dlt.sources.incremental) else year  # type: ignore[assignment]
    vars_ = _all_vars()
    vars_str = ",".join(vars_)
    base = _census_base_url(year_val)
    url = (
        f"{base}?get={vars_str}"
        f"&in=state:{state_fips}"
        f"&in=county:{county_fips}"
        f"&for=block%20group:*"
    )
    api_key = _census_api_key()
    if api_key:
        url += f"&key={api_key}"

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    data = response.json()
    headers = data[0]
    for row in data[1:]:
        record = dict(zip(headers, row, strict=False))
        record["year"] = year_val
        yield record


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
        ``{"success": True, "table_name": str, "row_count": int,
        "load_info": str}`` on success, or ``{"success": False,
        "error": str}`` on failure.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"census_acs_{state_fips}_{county_fips}_{year}",
        destination="postgres",
        dataset_name=schema,
    )

    try:
        load_info = pipeline.run(
            census_source(state_fips, county_fips, year),
        )

        row_count = 0
        if load_info.packages:  # type: ignore[attr-defined]
            last_pkg = load_info.packages[-1]  # type: ignore[attr-defined]
            for table_name, table_meta in last_pkg.tables.items():
                if table_name == "acs_raw":
                    row_count = table_meta.get("row_count", 0)
                    break

        return {
            "success": True,
            "table_name": f"{schema}.acs_raw",
            "row_count": row_count,
            "load_info": str(load_info),
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
