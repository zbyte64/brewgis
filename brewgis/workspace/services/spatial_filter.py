"""Layer filters — materialize a filter's matching rows as a new layer.

Applying a :class:`~brewgis.workspace.models.LayerFilter` never changes the
layer it filters. It materializes the rows the filter keeps as a **new table**
and registers that table as a new :class:`~brewgis.workspace.models.Layer`
(``LayerFilter.output_layer``); the filtered layer keeps drawing its own source.
The filter is applied exactly while that layer exists. Two blueprinted SQLMesh
models do the work:

* ``models/spatial_filter/spatial_filter.py`` — one model per *applied filter*,
  the filtered layer's rows matching the whole tree (column and spatial
  conditions alike, compiled by ``services.filter_compiler``).
* ``models/spatial_filter/spatial_filter_source.py`` — one model per *filter
  source* table (the other layer a spatial condition reads), copying its rows
  with the geometry projected into the region's local CRS under a fixed name and
  a GiST index on it.

Two models, not one, because a spatial join has to be index-driven. A filter
source is often a SQLMesh *view* (the virtual layer) — which Postgres cannot
index at all — and an imported table is usually unindexed, so probing it
row-by-row from the filtered layer is an O(rows x features) sequential scan.
Projecting each source once into an indexed table turns that into an index probe
per row. This is the project's standing rule for geometry joins ("never do
intersectional joins on non-indexed geometries ... provide a materialized table
projecting geometry onto a new indexed field");
``models/base_canvas/hwy_intersection_points.sql`` and its siblings are the same
pattern.

Naming — why the models live in ``spatial_filter`` rather than in the source's
own schema: SQLMesh names a model's physical object
``{schema}__{table}__{version}`` under the global ``SCHEMA_AND_TABLE``
convention, so a short fixed schema keeps
``spatial_filter__filter_<pk>__<hash>`` and ``spatial_filter__src_<hash>__<hash>``
far inside Postgres' 63-character identifier limit for any pk. That schema is
excluded from the table catalog (``services.sqlmesh_tables._EXCLUDED_SCHEMAS``)
— a filtered layer is reached through its own Layer, never imported as a source.

The module is imported by SQLMesh while it loads the project (the blueprint macro
and both models import from here), so it has **no Django or SQLMesh import at
module load**. Every symbol that needs either is imported inside the function
body that uses it.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from brewgis.workspace.models import Layer
    from brewgis.workspace.models import LayerFilter

# Schema holding the per-filter and per-source models.
SPATIAL_FILTER_SCHEMA = "spatial_filter"

# ``filter_json`` node type for a geospatial condition. Shared by both compilers
# (``services.filter_compiler``) and the filter-builder component's TypeScript
# union.
SPATIAL_NODE_TYPE = "spatial"

# Column a projected filter source carries its local-CRS geometry under. The
# filtered layer's predicate reads this column bare — that is what lets Postgres
# use the GiST index the source model creates on it.
PROJECTED_GEOMETRY_COLUMN = "sf_geometry"

# A ``spatial`` node's own keys: the ``schema.table`` it reads and that table's
# geometry column.
_SOURCE_KEY = "source"
_GEOMETRY_KEY = "source_geom"

# A ``spatial`` node's resolved projection model, injected by the blueprint macro
# (it is not part of the stored ``filter_json``, which the editor and the
# preview's MapLibre compiler also read).
FILTER_REF_KEY = "filter_ref"

# Geometry column assumed when a table has none registered in ``geometry_columns``.
_DEFAULT_GEOMETRY_COLUMN = "geometry"

# Must match ``services.sqlmesh_tables.SQLMESH_PROJECT_NAME`` — the catalog
# segment of every model FQN.
_SQLMESH_PROJECT_NAME = "brewgis"

# Hex characters of the source-identity digest kept in a source model's name.
_DIGEST_LENGTH = 8


class FilterNotMaterializableError(ValueError):
    """An applied filter the blueprints build no model for.

    Raised before a filtered layer is planned, so a layer is never registered
    over a table nothing creates.
    """


def filter_model_table(filter_pk: int) -> str:
    """Return the bare table name of *filter_pk*'s filtered-layer model."""
    return f"filter_{filter_pk}"


def filter_model_fqn(filter_pk: int) -> str:
    """SQLMesh's name for *filter_pk*'s filtered-layer model.

    Mirrors ``views.base_canvas._fill_model_fqn``: the identifier parts are
    double-quoted so the FQN survives selector parsing.
    """
    return f'brewgis."{SPATIAL_FILTER_SCHEMA}"."{filter_model_table(filter_pk)}"'


def filter_source_model_table(schema: str, table: str, geometry: str) -> str:
    """Return the bare table name of the projection model for a filter source.

    Keyed on the source's identity (schema, table and geometry column), so two
    filters reading the same table share one projection — and so the name is
    stable across plans, which is what lets SQLMesh reuse the built table
    instead of rebuilding it every time a filter is applied.
    """
    digest = hashlib.sha256(f"{schema}.{table}.{geometry}".encode()).hexdigest()
    return f"src_{digest[:_DIGEST_LENGTH]}"


def filter_source_model_fqn(schema: str, table: str, geometry: str) -> str:
    """SQLMesh's name for a filter source's projection model."""
    return (
        f'brewgis."{SPATIAL_FILTER_SCHEMA}"."'
        f'{filter_source_model_table(schema, table, geometry)}"'
    )


def _spatial_nodes(node: object) -> Iterator[dict[str, Any]]:
    """Yield every ``spatial`` node in the expression *node*, in tree order."""
    if not isinstance(node, dict):
        return
    if node.get("type") == SPATIAL_NODE_TYPE:
        yield node
        return
    for child in node.get("children") or []:
        yield from _spatial_nodes(child)


def filter_source_of_node(node: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return ``(schema, table, geometry)`` the ``spatial`` *node* reads.

    ``None`` when the node names no table — an unfinished condition in the
    editor. Such a filter gets no model rather than one over a table that does
    not exist.
    """
    source = str(node.get(_SOURCE_KEY) or "")
    schema, _, table = source.rpartition(".")
    if not table:
        return None
    geometry = str(node.get(_GEOMETRY_KEY) or _DEFAULT_GEOMETRY_COLUMN)
    return (schema or "public", table, geometry)


def filter_sources(filter_json: object) -> list[tuple[str, str, str]]:
    """``(schema, table, geometry)`` of every filter source *filter_json*'s spatial conditions read.

    Deduplicated and ordered, so a plan selection built from it is stable.
    """
    sources: dict[tuple[str, str, str], None] = {}
    for node in _spatial_nodes(filter_json):
        source = filter_source_of_node(node)
        if source is not None:
            sources[source] = None
    return list(sources)


def applied_filters() -> list[LayerFilter]:
    """Every filter that currently has a filtered layer, in pk order."""
    from brewgis.workspace.models import LayerFilter

    return list(
        LayerFilter.objects.filter(output_layer__isnull=False)
        .select_related("layer__workspace")
        .order_by("pk")
    )


def all_filter_sources() -> list[tuple[str, str, str]]:
    """``(schema, table, geometry)`` a projection model is needed for, deduplicated."""
    sources: dict[tuple[str, str, str], None] = {}
    for flt in applied_filters():
        for source in filter_sources(flt.filter_json):
            sources[source] = None
    return list(sources)


def with_filter_refs(node: Any, resolved: set[str]) -> Any | None:
    """Return a copy of *node* whose ``spatial`` nodes name their projection model.

    *resolved* is the set of projection tables the blueprints define. ``None``
    when any spatial condition reads a source without one — a model over it
    could only fail the plan. The stored ``filter_json`` is never modified: the
    editor and the preview compiler read it too.
    """
    if not isinstance(node, dict):
        return node
    if node.get("type") == SPATIAL_NODE_TYPE:
        source = filter_source_of_node(node)
        if source is None or filter_source_model_table(*source) not in resolved:
            return None
        return {**node, FILTER_REF_KEY: filter_source_model_fqn(*source)}
    children = node.get("children")
    if not isinstance(children, list):
        return node
    resolved_children = []
    for child in children:
        resolved_child = with_filter_refs(child, resolved)
        if resolved_child is None:
            return None
        resolved_children.append(resolved_child)
    return {**node, "children": resolved_children}


def quote_ident(name: str) -> str:
    """Double-quote *name* as a SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _positive_number(value: object) -> float | None:
    """Return *value* as a positive float, or ``None`` when it is absent/zero."""
    if not isinstance(value, (int, float, str)) or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def spatial_predicate(
    node: dict[str, Any],
    *,
    source_geom: str,
    local_srid: int,
    mpu: float,
) -> str:
    """Return the ``EXISTS`` (or negated) predicate for one ``spatial`` node.

    *source_geom* is the filtered layer's own geometry column (the model's
    ``src`` alias); the filter side is the node's projection model
    (``FILTER_REF_KEY``), whose ``PROJECTED_GEOMETRY_COLUMN`` is already in
    *local_srid* and indexed — so the probe is index-driven and this side is the
    only one transformed. *mpu* (see ``macros.geometry.metres_per_unit``)
    converts the node's buffer from metres to *local_srid*'s linear unit, so a
    buffer is never assumed to be metres.
    """
    mode = node.get("mode", "intersects")
    filter_ref = str(node[FILTER_REF_KEY])
    buffer_m = _positive_number(node.get("buffer_meters"))

    src_expr = f"ST_Transform(src.{quote_ident(source_geom)}, {local_srid})"
    flt_expr = f"f.{quote_ident(PROJECTED_GEOMETRY_COLUMN)}"
    if buffer_m is None:
        proximity = f"ST_Intersects({src_expr}, {flt_expr})"
    else:
        proximity = f"ST_DWithin({src_expr}, {flt_expr}, {buffer_m / mpu!r})"
    # filter_ref is a model FQN the macro already quoted, so it is used verbatim.
    exists = f"EXISTS (SELECT 1 FROM {filter_ref} AS f WHERE {proximity})"  # noqa: S608 (quoted FQN)
    return f"NOT {exists}" if mode == "excludes" else exists


def registered_geometry_column(schema: str, table: str) -> str | None:
    """Return the geometry column PostGIS registers for *table*, or ``None``.

    ``geometry_columns`` is authoritative and can list more than one geometry
    column (a raw ``geometry`` plus a reprojected ``local_geometry``); the
    conventional ``geometry`` is preferred, then the rest alphabetically, so the
    choice is stable.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT f_geometry_column FROM geometry_columns "
            "WHERE f_table_schema = %s AND f_table_name = %s "
            "ORDER BY (f_geometry_column = %s) DESC, f_geometry_column LIMIT 1",
            [schema, table, _DEFAULT_GEOMETRY_COLUMN],
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def geometry_column(schema: str, table: str) -> str:
    """Return *table*'s geometry column, falling back to ``geometry``.

    The fallback is for the filtered layer's *own* geometry (a table whose
    geometry column is not registered in ``geometry_columns`` still has the
    conventional one). Use :func:`registered_geometry_column` when the answer's
    existence matters — a filter layer with no registered geometry has nothing
    to intersect with.
    """
    return registered_geometry_column(schema, table) or _DEFAULT_GEOMETRY_COLUMN


def model_backed_table_ref(schema: str, table: str) -> str | None:
    """Return a model FQN a live SQLMesh model backs ``schema.table`` through.

    A table a model backs is named by its 3-part FQN
    (``brewgis.<schema>.<table>``) — and only that form, because the FQN is what
    satisfies SQLMesh's parser *and* records the real dependency on the model,
    which a bare ``schema.table`` over a virtual-layer view does not.
    """
    from brewgis.workspace.services.sqlmesh_tables import _model_backed_tables

    if (schema, table) in _model_backed_tables():
        return f"{_SQLMESH_PROJECT_NAME}.{schema}.{table}"
    return None


def table_ref(schema: str, table: str) -> str:
    """Return the FROM reference a filter model reads ``schema.table`` through.

    A model-backed table gets its FQN, which makes the filter model rebuild when
    that model's rows change; anything else (an imported shapefile, a table
    declared in ``external_models.yaml``) gets its bare ``schema.table``, which
    SQLMesh renders qualified against the project's catalog.
    """
    return model_backed_table_ref(schema, table) or f"{schema}.{table}"


def _purge_undefined_spatial_filter_models(defined_fqns: list[str]) -> list[str]:
    """De-list the filter models the project no longer defines.

    An un-applied filter, and a filter source no applied filter reads any more,
    both leave a snapshot behind that a later plan would try to promote —
    pointing a view at a physical object the plan never creates, which fails the
    whole plan. *defined_fqns* is exactly what the blueprint profiles currently
    emit, so anything else in the ``spatial_filter`` schema is stale. Mirrors
    ``services.scenario_canvas._purge_models_for_deleted_scenarios``.
    """
    from brewgis.workspace.analysis.sqlmesh_runner import get_state_context
    from brewgis.workspace.analysis.sqlmesh_runner import normalize_fqn
    from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
    from brewgis.workspace.analysis.sqlmesh_runner import snapshot_name

    defined = {normalize_fqn(fqn) for fqn in defined_fqns}
    prefix = f"{_SQLMESH_PROJECT_NAME}.{SPATIAL_FILTER_SCHEMA}."
    stale: list[str] = []
    for environment in get_state_context().state_sync.get_environments():
        for entry in environment.snapshots_:
            name = normalize_fqn(snapshot_name(entry))
            if name.startswith(prefix) and name not in defined:
                stale.append(name)
    if not stale:
        return []
    return purge_models_from_environments(stale)


def refresh_filter_models(flt: LayerFilter | None = None) -> None:
    """Bring the filter models in line with the applied filters.

    Models the blueprints no longer define are dropped from the environments
    first (a stale snapshot fails the plan that would promote it). With *flt*,
    its filtered-layer model and every filter source it reads are then planned —
    after applying it, or after editing an applied filter's tree. Mirrors
    ``views.base_canvas.SelectBaseCanvasForm.form_valid``'s fill toggle —
    plan/purge plus a Martin refresh.

    Raises:
        FilterNotMaterializableError: *flt* is applied but the blueprints define
            no model for it (its layer's table has no readable columns, or a
            spatial condition reads a layer with no registered geometry).

    No-op under tests: the SQLMesh state schema belongs to the running stack,
    not to the test database a test process builds layers in.
    """
    from django.conf import settings

    from brewgis.sqlmesh.macros.spatial_filter_blueprints import (
        spatial_filter_model_fqns,
    )
    from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
    from brewgis.workspace.services.tile_server import ensure_martin_source

    if settings.TESTING:
        return
    defined = spatial_filter_model_fqns()
    _purge_undefined_spatial_filter_models(defined)
    if flt is None:
        return
    if filter_model_fqn(flt.pk) not in defined:
        msg = (
            f"Filter {flt.name!r} cannot be materialized: the table of layer "
            f"{flt.layer.name or flt.layer.key!r} has no readable columns, or a "
            "spatial condition reads a layer with no registered geometry."
        )
        raise FilterNotMaterializableError(msg)
    run_sqlmesh_plan(
        environment="prod",
        select=[
            filter_model_fqn(flt.pk),
            *(
                filter_source_model_fqn(*source)
                for source in filter_sources(flt.filter_json)
            ),
        ],
        auto_apply=True,
        no_prompts=True,
    )
    if flt.layer.workspace.tile_server_backend == "martin":
        ensure_martin_source(f"{SPATIAL_FILTER_SCHEMA}.{filter_model_table(flt.pk)}")


def _copy_symbology(source: Layer, target: Layer) -> None:
    """Give *target* a copy of *source*'s symbology (config and classes), if it has one."""
    from brewgis.workspace.models import SymbologyConfig

    config = SymbologyConfig.objects.filter(layer=source).first()
    if config is None:
        return
    classes = list(config.classes.all())
    config.pk = None
    config.layer = target
    config.save()
    for style_class in classes:
        style_class.pk = None
        style_class.symbology = config
        style_class.save()


def apply_filter(flt: LayerFilter) -> Layer:
    """Materialize *flt*'s rows as a new layer; the filtered layer is untouched.

    The new layer sits beside its source — same group, scenario, geometry type
    and symbology — and draws ``spatial_filter.filter_<pk>``. Synchronous, like
    the base-canvas fill toggle: the table exists when this returns.
    """
    from brewgis.workspace.models import Layer

    source = flt.layer
    table = filter_model_table(flt.pk)
    layer = Layer.objects.create(
        workspace=source.workspace,
        key=table,
        name=f"{source.name or source.key} — {flt.name}",
        description=f"{source.name or source.key} filtered by “{flt.name}”.",
        geometry_type=source.geometry_type,
        layer_source=source.layer_source,
        db_schema=SPATIAL_FILTER_SCHEMA,
        db_table=table,
        group=source.group,
        scenario=source.scenario,
        display_order=source.display_order,
        source_filter=flt,
    )
    _copy_symbology(source, layer)
    refresh_filter_models(flt)
    return layer


def layer_owns_filter_models(layer: Layer) -> bool:
    """Whether deleting *layer* deletes a filtered layer, leaving a model to drop.

    True for a filtered layer itself, and for a layer with an applied filter
    (deleting it cascades to that filter and so to its filtered layer). Ask
    before the delete; call ``refresh_filter_models()`` after it.
    """
    return (
        layer.source_filter_id is not None
        or layer.filters.filter(output_layer__isnull=False).exists()
    )


def unapply_filter(flt: LayerFilter) -> None:
    """Delete *flt*'s filtered layer and drop the models nothing reads any more."""
    layer = flt.filtered_layer
    if layer is None:
        return
    layer.delete()
    refresh_filter_models()
