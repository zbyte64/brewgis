"""dlt pipeline for LEHD LODES WAC data extraction.

Replaces the raw CSV download portion of
``brewgis.workspace.services.lehd_fetcher`` with a dlt-based
pipeline that writes directly to a PostgreSQL staging table.
"""

from __future__ import annotations

import csv
import gzip
import io

import dlt
import requests

from brewgis.workspace.services.lehd_fetcher import (
    _FIPS_TO_STATE,
    LODES_WAC_BASE,
    LODES_WAC_VARIABLES,
)

__all__ = [
    "run_lehd_pipeline",
]


@dlt.resource(name="lodes_raw", write_disposition="replace")
def lehd_lodes_resource(state_fips, county_fips, year=2021):
    """Download LODES WAC gzipped CSV and yield rows as dicts."""
    state_abbr = _FIPS_TO_STATE.get(state_fips, "")
    if not state_abbr:
        raise ValueError(f"Unknown state FIPS: {state_fips}")

    url = f"{LODES_WAC_BASE}/{state_abbr}/wac/{state_abbr}_wac_S000_JT00_{year}.csv.gz"

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8")
        reader = csv.DictReader(text)
        for row in reader:
            cleaned = {k.strip(): v.strip() for k, v in row.items()}
            yield cleaned


def run_lehd_pipeline(state_fips, county_fips, year=2021, schema="public"):
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
            lehd_lodes_resource(state_fips, county_fips, year),
        )

        return {
            "success": True,
            "table_name": f"{schema}.lodes_raw",
            "row_count": 0,
            "load_info": str(load_info),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
