"""dlt-based data extraction pipelines for Brew GIS.

Each module exports a ``run_*_pipeline()`` function that uses dlt to
reliably extract raw data from an external API into a PostgreSQL staging
table. Domain-specific post-processing (geometry, column mapping,
derived columns) remains in the corresponding ``services/*_fetcher.py``
modules.
"""

from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
from brewgis.workspace.dlt_pipelines.poi import run_poi_pipeline

__all__ = [
    "run_census_pipeline",
    "run_lehd_pipeline",
    "run_poi_pipeline",
]
