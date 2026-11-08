"""Packaged base canvas — the base layer of a workspace imported from a package.

One instance per workspace imported from a workspace package: the workspace's
``base_table`` is ``wsp<pk>.base_canvas``, this model's view. It is the package's
``base_canvas`` part (bridged by ``workspace_inputs/packaged_base_canvas_raw.py``) with
the geometry re-tagged as the contract's ``GEOMETRY(MultiPolygon, 4326)``
(``BaseCanvasSchema.GEOMETRY_TYPE``) and the indexes every reader of a base
canvas probes: a GiST index on the geometry (canvas views, paint selection,
env_constraint's lateral probe, the tile servers) and a unique index on the
parcel key (paint overrides and every analysis join key on it).

Being a model, it is what the scenario canvases and the analysis models depend
on (``sqlmesh_tables.is_model_backed``), so a re-import rebuilds everything over
it in the same plan.
"""

# ruff: noqa: PLC0415 — see packaged_base_canvas_raw.py.

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.workspace_blueprints import workspace_subset_profiles

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

_PROFILES = workspace_subset_profiles("package_base")


def _column_descriptions() -> dict[str, str]:
    """The contract's label and unit for each column (no ``@``: see AGENTS.md)."""
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    descriptions: dict[str, str] = {}
    for name in BaseCanvasSchema.COLUMN_NAMES:
        column = BaseCanvasSchema.get(name)
        label = column.label if column is not None and column.label else name
        unit = f" ({column.unit})" if column is not None and column.unit else ""
        text = f"{label}{unit}."
        if name == "geometry":
            text = "Parcel boundary (MultiPolygon, EPSG:4326)."
        descriptions[name] = text.replace("@", " at ")
    return descriptions


_BASE_CANVAS_MODEL = model(
    name="brewgis.@{workspace_schema}.base_canvas",
    kind=ModelKindName.FULL,
    description=(
        "Base canvas of a workspace imported from a workspace package: one parcel"
        " per row with its geometry, area, people, housing and jobs, as the package"
        " shipped them."
    ),
    column_descriptions=_column_descriptions() if _PROFILES else {},
    depends_on=["brewgis.@{workspace_schema}.base_canvas_raw"],
    post_statements=[
        (
            "CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_geometry_') "
            "ON @this_model USING GIST (geometry)"
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS @snapshot_hash('idx_base_canvas_parcel_id_') "
            "ON @this_model USING btree (parcel_id)"
        ),
        "ANALYZE @this_model",
    ],
    blueprints=[dict(profile) for profile in _PROFILES],
    is_sql=True,
)


def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:  # noqa: ARG001
    """Re-tag the bridged geometry as the contract's type; pass every column through."""
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    schema = evaluator.blueprint_var("workspace_schema")
    columns = [
        f'"{name}"' for name in BaseCanvasSchema.COLUMN_NAMES if name != "geometry"
    ]
    geometry = (
        f"ST_Multi(ST_SetSRID(geometry, {BaseCanvasSchema.GEOMETRY_SRID}))"
        f"::{BaseCanvasSchema.GEOMETRY_TYPE} AS geometry"
    )
    return (
        f"SELECT {', '.join(columns)}, {geometry} "  # noqa: S608 — contract columns, model name
        f"FROM brewgis.{schema}.base_canvas_raw"
    )


execute = register_blueprint_model(_BASE_CANVAS_MODEL, execute, _PROFILES)
