"""Spatial filter — Python SQL model (blueprinted, one per filtered layer).

A layer whose active :class:`~brewgis.workspace.models.LayerFilter` tree contains
a ``spatial`` node cannot be filtered client-side, so this model materializes the
layer's spatially-filtered copy as a new table, and ``Layer.effective_source``
points the layer's tiles at it. One model per layer with an active spatial
filter, resolved while SQLMesh imports this module; the profiles — and the
reason the SELECT is assembled from them — are in
``macros/spatial_filter_blueprints.py``.

Each condition's filter side is a *projection* model
(``models/spatial_filter/spatial_filter_source.py``), not the raw other-layer
table: the projection carries the other table's geometry in the region's local
CRS behind a GiST index, which is what keeps this model's ``EXISTS`` an index
probe per row instead of a scan of a view (often not indexable at all). The
projection is named in the profile by
``services.spatial_filter.FILTER_REF_KEY``, so the stored ``filter_json`` — which
the client-side compiler also reads — stays free of it.

With no layer filtered there is nothing to instantiate and the module registers
no model at all — see :mod:`brewgis.sqlmesh.blueprint_models` for why an empty
list cannot be handed to ``@model`` instead.

No ``columns`` declaration and no ``column_descriptions``: the output's column
set is the per-layer source's, which SQLMesh infers through lineage (same
rationale as ``models/base_canvas/built_form_fill.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.geometry import metres_per_unit
from brewgis.sqlmesh.macros.geometry import require_local_srid
from brewgis.sqlmesh.macros.spatial_filter_blueprints import MODEL_SCHEMA
from brewgis.sqlmesh.macros.spatial_filter_blueprints import spatial_filter_profiles

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# ``metres_per_unit``/``require_local_srid`` are imported at *module* level, not
# inside ``execute`` as the other lazy imports are. SQLMesh decides which config
# variables a Python model's render context carries by statically parsing the
# entrypoint and the functions in its ``python_env`` (``parse_dependencies``) —
# and ``local_srid`` is only discovered by walking
# ``require_local_srid``'s own ``evaluator.var("local_srid")`` call. A
# function-local import keeps that function out of ``python_env``, so the render
# that evaluates the DDL's ``@execute()`` gets a context without the variable and
# the project stops loading with "The local_srid variable is not set" (the same
# reason ``models/adapters/assessor_parcels.py`` imports both at module level).

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per layer with an active spatial filter at that moment.
_PROFILES = spatial_filter_profiles()

# One declaration, applied once per filtered layer below: with no layer filtered
# there is nothing to instantiate.
_FILTER_MODEL = model(
    name=f"brewgis.{MODEL_SCHEMA}.@{{model_table}}",
    kind=ModelKindName.FULL,
    description=(
        "One layer's spatially-filtered copy: its source table rows that"
        " intersect (or are excluded from) the configured filter layer"
        " geometries, optionally within a distance buffer."
    ),
    # No ``number_of_rows`` audit, deliberately: with SQLMesh's threshold
    # semantics (``HAVING COUNT(*) <= threshold``) any threshold fails an empty
    # model, and an empty result is a legitimate outcome here — an ``excludes``
    # filter over a covering layer, or an ``intersects`` one whose filter layer
    # has no features nearby, both select zero rows and the layer should simply
    # draw nothing. The index below is what the tiles need.
    post_statements=[
        (
            "CREATE INDEX IF NOT EXISTS "
            "@snapshot_hash('idx_spatial_filter_geometry_') "
            "ON @this_model USING GIST (geometry)"
        ),
    ],
    blueprints=[dict(profile) for profile in _PROFILES],
    is_sql=True,
)


def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the layer's filtered SELECT.

    The returned string is not macro-rendered again by SQLMesh, so the blueprint
    variables are resolved here through the evaluator — including the source
    reference, which is a bare model FQN or ``schema.table`` and is used verbatim
    (SQLMesh snapshot-resolves a bare FQN when rendering the query).

    Only ``compile_spatial_predicate`` is imported inside ``execute``: SQLMesh
    imports this module while loading the project, where importing
    ``brewgis.workspace.services`` would pull in Django models before anything
    has configured Django. The geometry macros are module-level for the reason
    documented above.
    """
    from brewgis.workspace.services.spatial_filter import compile_spatial_predicate

    source_ref = str(evaluator.blueprint_var("source_ref"))
    source_geom = str(evaluator.blueprint_var("source_geom", "geometry"))
    raw_columns = evaluator.blueprint_var("all_columns", []) or []
    spatial_filters = evaluator.blueprint_var("spatial_filters", []) or []
    all_columns = [str(column) for column in raw_columns]

    local_srid = require_local_srid(evaluator)
    mpu = metres_per_unit(local_srid)

    # A spatial filter whose tree is only columns (impossible here — the profile
    # macro keeps only trees with a spatial node) contributes no predicate; the
    # layer's empty predicate list means "every row", the identity of the filter.
    predicates = [
        predicate
        for filter_json in spatial_filters
        if (
            predicate := compile_spatial_predicate(
                filter_json,
                source_geom=source_geom,
                local_srid=local_srid,
                mpu=mpu,
            )
        )
    ]
    where = " AND ".join(f"({predicate})" for predicate in predicates) or "TRUE"
    columns = ",\n    ".join(all_columns)

    return f"SELECT\n    {columns}\nFROM {source_ref} AS src\nWHERE {where}"


# One model per filtered layer: with none filtered, registering nothing is what
# keeps an empty blueprint list from becoming a phantom model.
execute = register_blueprint_model(_FILTER_MODEL, execute, _PROFILES)
