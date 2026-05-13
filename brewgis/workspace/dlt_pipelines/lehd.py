"""dlt pipeline for LEHD LODES WAC data extraction.

Downloads gzipped CSVs from the US Census LEHD API and loads them into
a PostgreSQL staging table via dlt.
"""

from __future__ import annotations

import csv
import gzip
import io

from typing import Any
import dlt
import requests

from brewgis.workspace.services.lehd_fetcher import (
    _FIPS_TO_STATE,
    LODES_WAC_BASE,
    LODES_WAC_VARIABLES,
)

__all__ = [
    "lehd_source",
    "run_lehd_pipeline",
]


@dlt.source(name="lehd_lodes", max_table_nesting=0)
def lehd_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: int,
) -> list[Any]:
    """dlt source for LEHD LODES WAC data extraction.

    Args:
        state_fips: Two-digit state FIPS code.
        county_fips: Three-digit county FIPS code.
        year: LEHD LODES release year.

    Returns:
        List with a single :class:`dlt.Resource` yielding WAC records
        as dicts keyed by CSV column name.
    """
    return [lehd_lodes_resource(state_fips, county_fips, year)]


@dlt.resource(
    name="lodes_raw",
    write_disposition="append",
    columns={
        "year": {"data_type": "bigint", "nullable": False},
    },
)
def lehd_lodes_resource(
    state_fips: str,
    county_fips: str,
    year: int,
) -> Any:
    """Download LODES WAC gzipped CSV and yield rows as dicts."""
    year_val: int = year
    state_abbr = _FIPS_TO_STATE.get(state_fips, "")
    if not state_abbr:
        raise ValueError(f"Unknown state FIPS: {state_fips}")

    url = f"{LODES_WAC_BASE}/{state_abbr}/wac/{state_abbr}_wac_S000_JT00_{year_val}.csv.gz"

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8")
        reader = csv.DictReader(text)
        for row in reader:
            cleaned = {k.strip(): v.strip() for k, v in row.items()}
            cleaned["year"] = year_val
            yield cleaned


def run_lehd_pipeline(
    state_fips: str,
    county_fips: str,
    year: int,
    schema: str = "public",
) -> dict[str, Any]:
    """Run dlt pipeline to extract raw LEHD LODES data to a staging table.

    Parameters
    ----------
    state_fips : str
        Two-digit state FIPS code.
    county_fips : str
        Three-digit county FIPS code.
    year : int
        LODES release year (default 2021).
    schema : str
        PostgreSQL schema for the destination table (default ``"public"``).

    Returns
    -------
    dict
        Keys: ``success``, ``table_name``, ``row_count``, ``load_info``
        (or ``error`` on failure).
    """
    try:
        pipeline = dlt.pipeline(
            pipeline_name=f"lehd_lodes_{state_fips}_{county_fips}_{year}",
            destination="postgres",
            dataset_name=schema,
        )

        load_info = pipeline.run(
            lehd_source(state_fips, county_fips, year),
        )

        row_count = 0
        for step in pipeline.last_trace.steps:
            si = step.step_info
            if hasattr(si, "row_counts") and si.row_counts:
                row_count = si.row_counts.get("lodes_raw", 0)
                break

        return {
            "success": True,
            "table_name": f"{schema}.lodes_raw",
            "row_count": row_count,
            "load_info": str(load_info),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
