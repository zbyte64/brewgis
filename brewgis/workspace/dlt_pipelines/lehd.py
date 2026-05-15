"""dlt pipeline for LEHD LODES WAC data extraction.

Downloads gzipped CSVs from the US Census LEHD API and loads them into
a PostgreSQL staging table via dlt.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
from typing import Any

import dlt
import requests

from brewgis.soda import validate_lehd
from brewgis.workspace.services.lehd_fetcher import _FIPS_TO_STATE
from brewgis.workspace.services.lehd_fetcher import LODES_WAC_BASE

__all__ = [
    "lehd_source",
    "run_lehd_pipeline",
]


logger = logging.getLogger(__name__)


@dlt.source(name="lehd_lodes", max_table_nesting=0)
def lehd_source(
    state_fips: str = "06",
    county_fips: str = "067",
    year: int = 2026,
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
    columns={
        "year": {"data_type": "bigint", "nullable": False},
    },
    primary_key=("year", "w_geocode"),
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
    # TODO purge entries that would cause duplicates, ie select matching fips & year then delete
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
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("lodes_raw", 0)
            break

    # Run Soda Core validation
    validation = validate_lehd(schema=schema, table="lodes_raw")
    if validation["success"]:
        logger.info("Validation passed for %s.lodes_raw", schema)
    else:
        msg = "; ".join(validation["failures"])
        raise RuntimeError(f"Validation failed for {schema}.lodes_raw: {msg}")

    return {
        "success": True,
        "table_name": f"{schema}.lodes_raw",
        "row_count": row_count,
        "load_info": str(load_info),
        "validation": validation,
    }
