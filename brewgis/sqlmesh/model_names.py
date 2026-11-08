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

WORKSPACE_SCHEMA_PREFIX = "wsp"
"""Schema segment holding one workspace's analysis-input models: ``wsp<workspace_pk>``.

Its base canvas (when the workspace was imported from a package), constraint
layers, trip-length zones, food outlets and road network — see
``macros/workspace_blueprints.py``. Short for the same reason as
``MODEL_SCHEMA_PREFIX``: SQLMesh's physical names are
``sqlmesh__<schema>.<schema>__<table>__<version>`` under Postgres' 63-character
identifier limit.
"""

SQLMESH_PROJECT_NAME = "brewgis"
"""Catalog/project the models are qualified with (see ``sqlmesh/config.py``)."""


def model_fqn(model_name: str, scenario_pk: int | str) -> str:
    """SQLMesh FQN of the per-scenario model *model_name* belongs to."""
    return f"{SQLMESH_PROJECT_NAME}.{MODEL_SCHEMA_PREFIX}{scenario_pk}.{model_name}"


def workspace_schema_name(workspace_pk: int | str) -> str:
    """Schema holding *workspace_pk*'s analysis-input models."""
    return f"{WORKSPACE_SCHEMA_PREFIX}{workspace_pk}"


def result_schema_name(scenario_id: int | str) -> str:
    """Schema holding *scenario_id*'s analysis result views."""
    return RESULT_SCHEMA_TEMPLATE.format(pk=scenario_id)
