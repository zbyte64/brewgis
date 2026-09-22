"""Naming scheme for the per-scenario blueprinted analysis models.

The analysis models are emitted once per scenario (see
``macros/analysis_blueprints.py``): the model lives in the internal
``ascn<scenario_pk>`` schema and publishes its result view at
``analysis__scenario_<pk>.<model name>`` — the location the Layers panel, the
tile servers and the UI read.

These names are shared by the SQLMesh macro that emits the models and the Django
side that selects them, so they live here — deliberately free of Django,
SQLMesh and sqlglot imports: the analysis module registry is imported on
ordinary request paths (map panels, MCP tools) that must not pay for a SQLMesh
import.
"""

from __future__ import annotations

MODEL_SCHEMA_PREFIX = "ascn"
"""Schema segment holding one scenario's analysis models: ``ascn<scenario_pk>``."""

RESULT_SCHEMA_PREFIX = "analysis__scenario_"
"""Prefix of the schema a scenario's analysis result views are published in."""

RESULT_SCHEMA_TEMPLATE = RESULT_SCHEMA_PREFIX + "{pk}"
"""Template for the result schema, formatted with the scenario primary key."""

SQLMESH_PROJECT_NAME = "brewgis"
"""Catalog/project the models are qualified with (see ``sqlmesh/config.py``)."""


def model_fqn(model_name: str, scenario_pk: int | str) -> str:
    """SQLMesh FQN of the per-scenario model *model_name* belongs to."""
    return f"{SQLMESH_PROJECT_NAME}.{MODEL_SCHEMA_PREFIX}{scenario_pk}.{model_name}"


def result_schema_name(scenario_id: int | str) -> str:
    """Schema holding *scenario_id*'s analysis result views."""
    return RESULT_SCHEMA_TEMPLATE.format(pk=scenario_id)
