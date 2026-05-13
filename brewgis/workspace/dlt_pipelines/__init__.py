"""dlt-based data extraction pipelines for Brew GIS.

Each submodule exports a ``*_source`` function (a ``@dlt.source`` for use
with ``@dlt_assets`` in Dagster) and a ``run_*_pipeline`` function (a
convenience wrapper for standalone Celery-task invocation).
"""

from __future__ import annotations

from brewgis.workspace.dlt_pipelines.census import census_source
from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
from brewgis.workspace.dlt_pipelines.lehd import lehd_source
from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
from brewgis.workspace.dlt_pipelines.poi import poi_source
from brewgis.workspace.dlt_pipelines.poi import run_poi_pipeline
from brewgis.workspace.dlt_pipelines.raster import raster_band_source
from brewgis.workspace.dlt_pipelines.raster import raster_metadata_source
from brewgis.workspace.dlt_pipelines.raster import run_raster_pipeline

__all__ = [
    "census_source",
    "lehd_source",
    "poi_source",
    "raster_band_source",
    "raster_metadata_source",
    "run_census_pipeline",
    "run_lehd_pipeline",
    "run_poi_pipeline",
    "run_raster_pipeline",
]
