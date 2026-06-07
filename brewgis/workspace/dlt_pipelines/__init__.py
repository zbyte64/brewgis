"""dlt-based data extraction pipelines for Brew GIS.

Each submodule exports a ``*_source`` function (a ``@dlt.source`` for use
with ``@dlt_assets``) and a ``run_*_pipeline`` function (a
convenience wrapper for standalone Celery-task invocation).
"""

from __future__ import annotations

from brewgis.workspace.dlt_pipelines.assessor import run_assessor_parcels_pipeline
from brewgis.workspace.dlt_pipelines.assessor import run_assessor_sales_pipeline
from brewgis.workspace.dlt_pipelines.census import census_source
from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
from brewgis.workspace.dlt_pipelines.lehd import lehd_source
from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline
from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline
from brewgis.workspace.dlt_pipelines.poi import poi_source
from brewgis.workspace.dlt_pipelines.poi import run_poi_pipeline
from brewgis.workspace.dlt_pipelines.raster import raster_band_source
from brewgis.workspace.dlt_pipelines.raster import raster_metadata_source
from brewgis.workspace.dlt_pipelines.raster import run_raster_pipeline
from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
from brewgis.workspace.dlt_pipelines.tiger_bg import tiger_bg_source
from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline
from brewgis.workspace.dlt_pipelines.tiger_block import tiger_block_source

__all__ = [
    "census_source",
    "lehd_source",
    "poi_source",
    "raster_band_source",
    "raster_metadata_source",
    "run_assessor_parcels_pipeline",
    "run_assessor_sales_pipeline",
    "run_census_pipeline",
    "run_lehd_pipeline",
    "run_nlcd_pipeline",
    "run_osm_pipeline",
    "run_poi_pipeline",
    "run_raster_pipeline",
    "run_tiger_bg_pipeline",
    "run_tiger_block_pipeline",
    "tiger_bg_source",
    "tiger_block_source",
]
