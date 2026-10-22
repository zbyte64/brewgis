"""Packaged base canvas bridge — DuckDB reads the package's base layer into PostGIS.

One instance per workspace imported from a workspace package
(``services.workspace_package``): the ``base_canvas`` part, a GeoParquet file of
every base-canvas column, read by DuckDB straight from the unpacked package and
written to PostGIS. Like every DuckDB bridge its geometry lands as SRID 0 (the
transfer writes SRID-less WKB — see ``workspace_inputs/food_pois_fetch_raw.sql``),
so nothing reads this table but ``workspace_inputs/packaged_base_canvas.py``, which
re-tags it.

The column list is the base-canvas contract (``BaseCanvasSchema.COLUMN_NAMES``)
of *this* server: the import refuses a package that does not carry every one of
them, so a column the exporting server had and this one does not is left out
rather than carried into a table no canvas view reads. Each column keeps the
type the package wrote it at — the exporting table's own type — so an APN stays
text and a geography id stays an integer.

A Python SQL model rather than a ``.sql`` file because the column list and the
column descriptions are the contract's, read at load time.
"""

# ruff: noqa: PLC0415 — ``BaseCanvasSchema`` imports Django models, and SQLMesh
# imports this module while loading the project; the profiles call sets Django up.

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.workspace_blueprints import workspace_subset_profiles

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# One entry per workspace imported from a package, at load time.
_PROFILES = workspace_subset_profiles("package_base")


def _column_descriptions() -> dict[str, str]:
    """The contract's label and unit for each column (no ``@``: see AGENTS.md)."""
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    descriptions: dict[str, str] = {}
    for name in BaseCanvasSchema.COLUMN_NAMES:
        column = BaseCanvasSchema.get(name)
        label = column.label if column is not None and column.label else name
        unit = f" ({column.unit})" if column is not None and column.unit else ""
        text = f"{label}{unit}, as the workspace package carried it."
        if name == "geometry":
            text = (
                "Parcel boundary in EPSG:4326 stored as SRID 0 (the DuckDB-to-PostGIS "
                "transfer writes SRID-less WKB); the base_canvas model re-tags it."
            )
        descriptions[name] = text.replace("@", " at ")
    return descriptions


_BASE_CANVAS_RAW_MODEL = model(
    name="brewgis.@{workspace_schema}.base_canvas_raw",
    kind=ModelKindName.FULL,
    gateway="duckdb",
    dialect="duckdb",
    description=(
        "Base layer shipped in the workspace package, read by DuckDB from the"
        " package GeoParquet into PostGIS, one parcel per row."
    ),
    column_descriptions=_column_descriptions() if _PROFILES else {},
    blueprints=[dict(profile) for profile in _PROFILES],
    is_sql=True,
)


def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:  # noqa: ARG001
    """Select the contract's columns from the package's base canvas part."""
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

    path = str(evaluator.blueprint_var("base_canvas_parquet")).replace("'", "''")
    columns = [
        f'"{name}"' for name in BaseCanvasSchema.COLUMN_NAMES if name != "geometry"
    ]
    return (
        f"SELECT {', '.join(columns)}, ST_SetCRS(geometry, 'EPSG:4326') AS geometry "  # noqa: S608 — contract columns, project-owned path
        f"FROM read_parquet('{path}')"
    )


execute = register_blueprint_model(_BASE_CANVAS_RAW_MODEL, execute, _PROFILES)
