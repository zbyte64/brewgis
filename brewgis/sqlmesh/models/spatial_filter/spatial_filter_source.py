"""Spatial filter source — Python SQL model (blueprinted, one per filter source).

A geospatial filter condition reads another layer's geometry, and that read has
to be index-driven: the other layer is often a SQLMesh *view* (which Postgres
cannot index) or an unindexed import, so probing it once per row of the filtered
layer is an O(rows x features) sequential scan. This model is the fix prescribed
by the project's geometry-join rule — it copies the source table with the geometry
projected into the region's local CRS under ``sf_geometry`` and a GiST index on
it, so the filtered layer's ``EXISTS`` becomes an index probe per row.

One model per *filter source* (the source's schema, table and geometry column —
see ``services.spatial_filter.filter_source_model_table``), shared by every
condition that reads the same table, resolved while SQLMesh imports this module.
With no active spatial filter there is nothing to instantiate and the module
registers no model at all — see :mod:`brewgis.sqlmesh.blueprint_models` for why
an empty list cannot be handed to ``@model`` instead.

The projection is what makes the pair work: the layer model filters
``ST_Transform(<its geometry>, local_srid)`` against this table's
``sf_geometry``, so both sides are in one planar CRS and the buffer conversion
(``macros.geometry.metres_per_unit``) is the only place a unit is assumed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.geometry import require_local_srid
from brewgis.sqlmesh.macros.spatial_filter_blueprints import MODEL_SCHEMA
from brewgis.sqlmesh.macros.spatial_filter_blueprints import (
    spatial_filter_source_profiles,
)

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# The projected geometry's column name and the region's projection both come from
# the service, so the layer model's predicate and this model cannot disagree on
# either. ``require_local_srid`` is a *module-level* import because SQLMesh
# decides which config variables a Python model's render context carries by
# statically parsing the entrypoint and its ``python_env`` (``parse_dependencies``)
# — the only way it can learn about ``local_srid`` is by walking that function.
from brewgis.workspace.services.spatial_filter import PROJECTED_GEOMETRY_COLUMN
from brewgis.workspace.services.spatial_filter import quote_ident

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per filter source an active spatial filter reads at that moment.
_PROFILES = spatial_filter_source_profiles()

_SOURCE_MODEL = model(
    name=f"brewgis.{MODEL_SCHEMA}.@{{source_model_table}}",
    kind=ModelKindName.FULL,
    description=(
        "One spatial filter source's rows with its geometry projected into the"
        " region's local CRS (column sf_geometry) and GiST-indexed, so a"
        " filtered layer's spatial predicate probes it by index."
    ),
    post_statements=[
        (
            "CREATE INDEX IF NOT EXISTS "
            f"@snapshot_hash('idx_spatial_filter_src_{PROJECTED_GEOMETRY_COLUMN}_') "
            f"ON @this_model USING GIST ({PROJECTED_GEOMETRY_COLUMN})"
        ),
    ],
    blueprints=[dict(profile) for profile in _PROFILES],
    is_sql=True,
)


def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the filter source's projected SELECT.

    The returned string is not macro-rendered again by SQLMesh, so the blueprint
    variables are resolved here through the evaluator — including the source
    reference, which is a bare model FQN or ``schema.table`` and is used verbatim
    (SQLMesh snapshot-resolves a bare FQN when rendering the query).

    The column list is spelled out rather than ``*`` so SQLMesh can infer this
    model's columns: the source may be a plain table with no SQLMesh contract,
    and a schema it cannot introspect would leave the projection's columns
    unknown to every downstream model.
    """
    source_ref = str(evaluator.blueprint_var("source_ref"))
    source_geom = str(evaluator.blueprint_var("source_geom"))
    raw_columns = evaluator.blueprint_var("all_columns", []) or []
    local_srid = require_local_srid(evaluator)

    columns = ",\n    ".join(f"sf.{quote_ident(str(column))}" for column in raw_columns)
    projection = f"ST_Transform(sf.{quote_ident(source_geom)}, {local_srid})"

    return (
        f"SELECT\n    {columns},\n"
        f"    {projection} AS {PROJECTED_GEOMETRY_COLUMN}\n"
        f"FROM {source_ref} AS sf"
    )


# One model per filter source: with none needed, registering nothing is what
# keeps an empty blueprint list from becoming a phantom model.
execute = register_blueprint_model(_SOURCE_MODEL, execute, _PROFILES)
