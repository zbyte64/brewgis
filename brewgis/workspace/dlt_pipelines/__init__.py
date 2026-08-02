"""Data pipeline modules for Brew GIS.

Each submodule exports a ``run_*_pipeline`` convenience function for
standalone Celery-task invocation.
"""

from __future__ import annotations

from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline

__all__ = [
    "run_osm_pipeline",
]
