"""dlt pipeline assets via ``@dlt_assets`` decorator.

Wraps the existing 3 dlt pipelines (census ACS, LEHD LODES WAC, Overpass POI)
plus the raster pipeline as Dagster software-defined assets. Each asset group
corresponds to one dlt source and produces a staging table in PostGIS.
"""

from __future__ import annotations

from typing import Any

import dlt
from dagster import AssetExecutionContext
from dagster_embedded_elt.dlt import DagsterDltResource
from dagster_embedded_elt.dlt import dlt_assets

from brewgis.workspace.dlt_pipelines.census import census_source
from brewgis.workspace.dlt_pipelines.lehd import lehd_source
from brewgis.workspace.dlt_pipelines.poi import poi_source
from brewgis.workspace.dlt_pipelines.raster import raster_band_source
from brewgis.workspace.dlt_pipelines.raster import raster_metadata_source

_STAGING_SCHEMA = "public"


# ---------------------------------------------------------------------------
# Census ACS
# ---------------------------------------------------------------------------

@dlt_assets(
    dlt_source=census_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="census_acs",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
)
def census_acs_assets(context: AssetExecutionContext, dlt: DagsterDltResource) -> Any:
    """Materialize raw Census ACS 5-year data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# LEHD LODES WAC
# ---------------------------------------------------------------------------

@dlt_assets(
    dlt_source=lehd_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="lehd_lodes",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
)
def lehd_lodes_assets(context: AssetExecutionContext, dlt: DagsterDltResource) -> Any:
    """Materialize raw LEHD LODES WAC data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Overpass POI
# ---------------------------------------------------------------------------

@dlt_assets(
    dlt_source=poi_source(),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="overpass_poi",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raw_data",
)
def overpass_poi_assets(context: AssetExecutionContext, dlt: DagsterDltResource) -> Any:
    """Materialize raw Overpass POI data into PostGIS staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Raster metadata
# ---------------------------------------------------------------------------

@dlt_assets(
    dlt_source=raster_metadata_source(file_path=""),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="raster_metadata",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raster",
)
def raster_metadata_assets(context: AssetExecutionContext, dlt: DagsterDltResource) -> Any:
    """Extract GeoTIFF/COG metadata (width, height, CRS, bounds) to staging."""
    yield from dlt.run(context=context)


# ---------------------------------------------------------------------------
# Raster band statistics
# ---------------------------------------------------------------------------

@dlt_assets(
    dlt_source=raster_band_source(file_path=""),
    dlt_pipeline=dlt.pipeline(
        pipeline_name="raster_bands",
        destination="postgres",
        dataset_name=_STAGING_SCHEMA,
    ),
    group_name="raster",
)
def raster_band_assets(context: AssetExecutionContext, dlt: DagsterDltResource) -> Any:
    """Extract per-band statistics (min, max, mean, stddev) from GeoTIFF."""
    yield from dlt.run(context=context)
