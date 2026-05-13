"""Dagster orchestration for Brew GIS data pipelines.

Provides asset definitions, resources, schedules, and sensors that
orchestrate dlt extraction, dbt transformation, and spatial analysis
within Dagster's asset graph. Coexists with Celery for non-pipeline
async tasks (email, notifications).
"""

from __future__ import annotations
