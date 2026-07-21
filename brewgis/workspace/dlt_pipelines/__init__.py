"""Data pipeline modules for Brew GIS.

Each submodule exports a ``run_*_pipeline`` convenience function for
standalone Celery-task invocation.
"""

from __future__ import annotations

from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline
from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_tree_canopy_pipeline
from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline

__all__ = [
    "run_nlcd_pipeline",
    "run_nlcd_tree_canopy_pipeline",
    "run_osm_pipeline",
]
