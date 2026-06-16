"""dlt pipeline for Census 2020 Decennial P.L. 94-171 block-level data.

Extracts total population (P1_001N) and total housing units (H1_001N) at
the census block level from the 2020 decennial Census API for a given
state and county. Writes to a PostgreSQL staging table via dlt with
replace disposition since the decennial census is a point-in-time dataset.

The Census API returns a JSON array where the first element is the header
row and subsequent elements are data rows. Each data row contains the
requested variables plus geography identifiers (state, county, tract,
block). A 15-digit GEOID is constructed from the concatenated FIPS codes.
"""

from __future__ import annotations

import json
import logging

__all__ = [
    "census_2020_block_source",
    "run_census_2020_pipeline",
]

from pathlib import Path
from typing import Any

import dlt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR

_SENTINELS = frozenset({"-666666666", "-555555555", "-333333333"})

_BASE_URL = "https://api.census.gov/data/2020/dec/pl"


@dlt.source(name="census_2020_block", max_table_nesting=0)
def census_2020_block_source(
    state_fips: str = "06",
    county_fips: str = "067",
    ignore_cache: bool = False,
) -> list[Any]:
    """dlt source for Census 2020 Decennial P.L. 94-171 block extraction.

    Args:
        state_fips: Two-digit state FIPS code (default ``"06"``).
        county_fips: Three-digit county FIPS code (default ``"067"``).
        ignore_cache: Re-download even if cached.

    Returns:
        List with a single :class:`dlt.Resource` yielding block-level dicts
        with ``geoid`` (15-digit), ``total_population``, and
        ``total_housing_units``.
    """
    return [
        census_2020_block_resource(state_fips, county_fips, ignore_cache),
    ]


@dlt.resource(
    name="census_2020_block_raw",
    table_name="census_2020_block_raw",
    write_disposition="replace",
    primary_key=("geoid",),
    columns={
        "geoid": {"data_type": "text", "nullable": False},
        "total_population": {"data_type": "bigint", "nullable": True},
        "total_housing_units": {"data_type": "bigint", "nullable": True},
        "state": {"data_type": "text", "nullable": False},
        "county": {"data_type": "text", "nullable": False},
    },
)
def census_2020_block_resource(
    state_fips: str,
    county_fips: str,
    ignore_cache: bool = False,
) -> Any:
    """Yield Census 2020 Decennial P.L. 94-171 data, one dict per block.

    Uses replace write disposition since the decennial census is a
    point-in-time dataset with no incremental key.

    The Census API response format is a JSON array-of-arrays: the first
    row contains column names (e.g. ``["P1_001N", "H1_001N", "state",
    "county", "tract", "block"]``) and subsequent rows contain the
    corresponding values.
    """
    dl_path = CACHE_DIR / "census_2020" / state_fips / f"{county_fips}.json"
    dl_path.parent.mkdir(exist_ok=True, parents=True)

    # Try loading from local JSON cache first
    data: Any = None
    if not ignore_cache and dl_path.exists():
        with dl_path.open() as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(
                "Cached Census 2020 data is %s instead of list, re-downloading",
                type(data).__name__,
            )
            data = None

    if data is None:
        vars_str = "P1_001N,H1_001N"
        url = (
            f"{_BASE_URL}?get={vars_str}"
            f"&for=block:*"
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
                f"Census 2020 API returned {type(data).__name__} instead of list. "
                f"Status: {response.status_code}, URL: {response.url}, "
                f"Body: {response.text[:500]}"
            )
        with dl_path.open("w") as f:
            json.dump(data, f)

    headers = data[0]
    for row in data[1:]:
        record: dict[str, Any] = dict(zip(headers, row, strict=False))

        # Build 15-digit GEOID from component FIPS codes
        geoid = f"{record['state']}{record['county']}{record['tract']}{record['block']}"

        # Convert sentinel values to None
        total_pop: int | None = None
        total_hu: int | None = None

        p1 = record.get("P1_001N")
        if isinstance(p1, str) and p1 not in _SENTINELS:
            try:
                total_pop = int(p1)
            except (ValueError, TypeError):
                pass

        h1 = record.get("H1_001N")
        if isinstance(h1, str) and h1 not in _SENTINELS:
            try:
                total_hu = int(h1)
            except (ValueError, TypeError):
                pass

        yield {
            "geoid": geoid,
            "total_population": total_pop,
            "total_housing_units": total_hu,
            "state": state_fips,
            "county": county_fips,
        }


def run_census_2020_pipeline(
    state_fips: str = "06",
    county_fips: str = "067",
    schema: str = "public",
    ignore_cache: bool = False,
    **kwargs: Any,
) -> dict:
    """Run dlt pipeline to extract Census 2020 block-level data.

    Fetches total population and housing units at the block level for a
    given state and county from the Census 2020 Decennial P.L. 94-171 API
    and writes the results to a PostgreSQL staging table.

    Parameters
    ----------
    state_fips : str, optional
        Two-digit state FIPS code (default ``"06"`` for California).
    county_fips : str, optional
        Three-digit county FIPS code (default ``"067"`` for Sacramento).
    schema : str, optional
        PostgreSQL schema for the destination table (default ``"public"``).
    ignore_cache : bool, optional
        Re-download data even if cached.

    Returns
    -------
    dict
        ``{"table_name": str, "row_count": int, "load_info": str}``.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"census_2020_block_{state_fips}_{county_fips}",
        destination="postgres",
        dataset_name=schema,
        **kwargs,
    )

    load_info = pipeline.run(
        census_2020_block_source(state_fips, county_fips, ignore_cache=ignore_cache),
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if si is not None and hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("census_2020_block_raw", 0)
            break

    return {
        "table_name": f"{schema}.census_2020_block_raw",
        "row_count": row_count,
        "load_info": str(load_info),
    }
