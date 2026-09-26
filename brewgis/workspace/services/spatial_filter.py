"""Geospatial layer filters — materialize a spatially-filtered copy of a layer.

A :class:`~brewgis.workspace.models.LayerFilter` whose tree contains a
``spatial`` node cannot be evaluated client-side: MapLibre filters are pure
column expressions and have no way to intersect a tile feature with another
layer's geometry. Such a filter therefore materializes **new tables** that the
layer then draws from (``Layer.effective_source``):

* ``models/spatial_filter/spatial_filter_source.py`` — one model per *filter
  source* table (the other layer a condition reads), copying its rows with the
  geometry projected into the region's local CRS under a fixed name and a GiST
  index on it.
* ``models/spatial_filter/spatial_filter.py`` — one model per *filtered layer*,
  its source rows that intersect (or are excluded from) the projected filter
  geometries, optionally within a distance buffer.

Two models, not one, because the join has to be index-driven. A filter source is
often a SQLMesh *view* (the virtual layer) — which Postgres cannot index at all
— and an imported table is usually unindexed, so probing it row-by-row from the
filtered layer is an O(rows x features) sequential scan. Projecting each source
once into an indexed table turns that into an index probe per row. This is the
project's standing rule for geometry joins ("never do intersectional joins on
non-indexed geometries ... provide a materialized table projecting geometry onto
a new indexed field"); ``models/base_canvas/hwy_intersection_points.sql`` and its
siblings are the same pattern.

Naming — why the models live in ``spatial_filter`` rather than in the source's
own schema: SQLMesh names a model's physical object
``{schema}__{table}__{version}`` under the global ``SCHEMA_AND_TABLE``
convention, so a short fixed schema keeps
``spatial_filter__filter_<pk>__<hash>`` and ``spatial_filter__src_<hash>__<hash>``
far inside Postgres' 63-character identifier limit for any pk. That schema is
excluded from the table catalog (``services.sqlmesh_tables._EXCLUDED_SCHEMAS``)
— a derived copy is not itself an importable source.

The module is imported by SQLMesh while it loads the project (the blueprint macro
imports ``SPATIAL_FILTER_SCHEMA`` and ``has_spatial_node`` from here), so it has
**no Django or SQLMesh import at module load**. Every symbol that needs either is
imported inside the function body that uses it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterator

    from brewgis.workspace.models import Layer

# Schema holding the per-layer and per-source spatial-filter models.
SPATIAL_FILTER_SCHEMA = "spatial_filter"

# ``filter_json`` node type for a geospatial condition. Shared by the SQL
# compiler here, the client-side compiler (``services.filter_compiler``) and the
# filter-builder component's TypeScript union.
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
# (it is not part of the stored ``filter_json``, which the client-side compiler
# also reads).
FILTER_REF_KEY = "filter_ref"

# Geometry column assumed when a table has none registered in ``geometry_columns``.
_DEFAULT_GEOMETRY_COLUMN = "geometry"

# Must match ``services.sqlmesh_tables.SQLMESH_PROJECT_NAME`` — the leading
# segment of every external-model name that is already project-qualified.
_SQLMESH_PROJECT_NAME = "brewgis"

# An external model's name reduces to at least ``schema.table`` once the project
# segment is dropped.
_MIN_TABLE_PARTS = 2

# Hex characters of the source-identity digest kept in a source model's name.
_DIGEST_LENGTH = 8

_SPATIAL_TYPES = frozenset({SPATIAL_NODE_TYPE})


def filter_model_table(layer_pk: int) -> str:
    """Return the bare table name of *layer_pk*'s spatial-filter model."""
    return f"filter_{layer_pk}"


def filter_model_fqn(layer_pk: int) -> str:
    """SQLMesh's name for *layer_pk*'s spatial-filter model.

    Mirrors ``views.base_canvas._fill_model_fqn``: the identifier parts are
    double-quoted so the FQN survives selector parsing.
    """
    return f'brewgis."{SPATIAL_FILTER_SCHEMA}"."{filter_model_table(layer_pk)}"'


def filter_source_model_table(schema: str, table: str, geometry: str) -> str:
    """Return the bare table name of the projection model for a filter source.

    Keyed on the source's identity (schema, table and geometry column), so two
    layers filtering against the same table share one projection — and so the
    name is stable across plans, which is what lets SQLMesh reuse the built
    table instead of rebuilding it on every filter toggle.
    """
    digest = hashlib.sha256(f"{schema}.{table}.{geometry}".encode()).hexdigest()
    return f"src_{digest[:_DIGEST_LENGTH]}"


def filter_source_model_fqn(schema: str, table: str, geometry: str) -> str:
    """SQLMesh's name for a filter source's projection model."""
    return (
        f'brewgis."{SPATIAL_FILTER_SCHEMA}"."'
        f'{filter_source_model_table(schema, table, geometry)}"'
    )


def has_spatial_node(node: object) -> bool:
    """Whether the expression *node* contains a ``spatial`` condition anywhere.

    Walks groups recursively; a non-dict, a non-group leaf, and an empty group
    all answer ``False``.
    """
    if not isinstance(node, dict):
        return False
    if node.get("type") in _SPATIAL_TYPES:
        return True
    children = node.get("children")
    if isinstance(children, list):
        return any(has_spatial_node(child) for child in children)
    return False


def _spatial_nodes(node: object) -> Iterator[dict[str, Any]]:
    """Yield every ``spatial`` node in the expression *node*, in tree order."""
    if not isinstance(node, dict):
        return
    if node.get("type") in _SPATIAL_TYPES:
        yield node
        return
    for child in node.get("children") or []:
        yield from _spatial_nodes(child)


def filter_source_of_node(node: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return ``(schema, table, geometry)`` the ``spatial`` *node* reads.

    ``None`` when the node names no table — an unfinished condition in the
    editor. Callers skip such a node rather than build a model over a table that
    does not exist.
    """
    source = str(node.get(_SOURCE_KEY) or "")
    schema, _, table = source.rpartition(".")
    if not table:
        return None
    geometry = str(node.get(_GEOMETRY_KEY) or _DEFAULT_GEOMETRY_COLUMN)
    return (schema or "public", table, geometry)


def layer_spatial_nodes(layer: Layer) -> list[dict[str, Any]]:
    """Every active ``spatial`` node on *layer*, in filter/child order."""
    return [
        node
        for filter_json in active_spatial_filter_jsons(layer)
        for node in _spatial_nodes(filter_json)
    ]


def layer_filter_sources(layer: Layer) -> list[tuple[str, str, str]]:
    """``(schema, table, geometry)`` of every filter source *layer*'s conditions read.

    Deduplicated and ordered, so a plan selection built from it is stable.
    """
    sources: dict[tuple[str, str, str], None] = {}
    for node in layer_spatial_nodes(layer):
        source = filter_source_of_node(node)
        if source is not None:
            sources[source] = None
    return list(sources)


def spatial_nodes() -> dict[Layer, list[dict[str, Any]]]:
    """Every layer with an active spatial filter, mapped to its ``spatial`` nodes."""
    from brewgis.workspace.models import Layer

    layers = Layer.objects.select_related("workspace").order_by("pk")
    grouped: dict[Layer, list[dict[str, Any]]] = {}
    for layer in layers:
        nodes = layer_spatial_nodes(layer)
        if nodes:
            grouped[layer] = nodes
    return grouped


def all_filter_sources() -> list[tuple[str, str, str]]:
    """``(schema, table, geometry)`` a projection model is needed for, deduplicated."""
    sources: dict[tuple[str, str, str], None] = {}
    for nodes in spatial_nodes().values():
        for node in nodes:
            source = filter_source_of_node(node)
            if source is not None:
                sources[source] = None
    return list(sources)


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


def _spatial_predicate(
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


def _walk_spatial(
    node: dict[str, Any],
    *,
    source_geom: str,
    local_srid: int,
    mpu: float,
) -> str | None:
    """Return the spatial SQL for *node*, or ``None`` when it contributes none.

    A ``column`` (or any other leaf) is evaluated client-side over the filtered
    table, so it is skipped here rather than compiled. A group is ``None`` when
    none of its children contribute.
    """
    node_type = node.get("type")
    if node_type in _SPATIAL_TYPES:
        return _spatial_predicate(
            node, source_geom=source_geom, local_srid=local_srid, mpu=mpu
        )
    if node_type != "group":
        return None
    parts = [
        part
        for child in node.get("children") or []
        if isinstance(child, dict)
        and (
            part := _walk_spatial(
                child, source_geom=source_geom, local_srid=local_srid, mpu=mpu
            )
        )
        is not None
    ]
    if not parts:
        return None
    operator = node.get("operator", "AND")
    return f"({f' {operator} '.join(parts)})"


def compile_spatial_predicate(
    filter_json: dict[str, Any] | None,
    *,
    source_geom: str,
    local_srid: int,
    mpu: float,
) -> str:
    """Compile the spatial part of *filter_json* to a SQL WHERE fragment.

    *source_geom* is the filtered layer's own geometry column (the model's
    ``src`` alias); *local_srid* and *mpu* are the region's projection and its
    metres-per-unit factor. Every ``spatial`` node must carry its
    ``FILTER_REF_KEY`` (the blueprint macro resolves it), so the tree is the
    *profile's* copy, not a stored ``filter_json``.

    Returns ``""`` when the tree has no ``spatial`` node, so a purely
    column-side filter contributes no WHERE clause.
    """
    if not isinstance(filter_json, dict):
        return ""
    return (
        _walk_spatial(
            filter_json, source_geom=source_geom, local_srid=local_srid, mpu=mpu
        )
        or ""
    )


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


def active_spatial_filter_jsons(layer: Layer) -> list[dict[str, Any]]:
    """Return the ``filter_json`` of *layer*'s active spatial filters, in pk order."""
    return [
        flt.filter_json
        for flt in layer.filters.filter(is_active=True).order_by("pk")
        if has_spatial_node(flt.filter_json)
    ]


def layer_has_active_spatial_filter(layer: Layer) -> bool:
    """Whether *layer* draws from a materialized filter table right now."""
    return bool(active_spatial_filter_jsons(layer))


def external_model_tables() -> frozenset[tuple[str, str]]:
    """``(schema, table)`` of every table SQLMesh knows through ``external_models.yaml``.

    The file names each external table as a SQLMesh FQN — ``'"brewgis"."public"."base_canvas"'``
    (project-qualified) or ``public.sacog_comparison_parcels`` (bare) — so the
    project segment is dropped and the last two parts are the table's identity.
    """
    import yaml

    path = Path(__file__).resolve().parents[2] / "sqlmesh" / "external_models.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    tables: set[tuple[str, str]] = set()
    for entry in entries:
        parts = [
            part.strip().strip('"') for part in str(entry.get("name", "")).split(".")
        ]
        if parts and parts[0] == _SQLMESH_PROJECT_NAME:
            parts = parts[1:]
        if len(parts) >= _MIN_TABLE_PARTS:
            tables.add((parts[-2], parts[-1]))
    return frozenset(tables)


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


def source_ref_for_layer(schema: str, table: str) -> str | None:
    """Return the FROM reference a *filtered layer* model may read ``schema.table`` through.

    A model-backed table is named by its 3-part FQN, a table declared in
    ``external_models.yaml`` by its bare ``schema.table``. Anything else (an
    ad-hoc imported shapefile in ``public``, say) has no reference the layer
    model may use, so ``None`` — the caller skips that layer with a warning
    rather than emitting a model that cannot carry the layer's other rows.
    """
    ref = model_backed_table_ref(schema, table)
    if ref is not None:
        return ref
    if (schema, table) in external_model_tables():
        return f"{schema}.{table}"
    return None


def filter_source_ref(schema: str, table: str) -> str:
    """Return the FROM reference a *filter source* model may read ``schema.table`` through.

    Unlike a filtered layer's source, a filter source only has to be readable:
    the projection copies its rows and adds no dependency the caller cares about,
    so every table qualifies. A model-backed table still gets its FQN (that is
    what makes the projection rebuild when the model's rows change); anything
    else gets its bare ``schema.table``, which SQLMesh renders qualified against
    the project's catalog.
    """
    return model_backed_table_ref(schema, table) or f"{schema}.{table}"


def _purge_undefined_spatial_filter_models() -> list[str]:
    """De-list the spatial-filter models the project no longer defines.

    A layer whose last spatial filter was switched off, and a filter source no
    active spatial filter references any more, both leave a snapshot behind that
    a later plan would try to promote — pointing a view at a physical object the
    plan never creates, which fails the whole plan. The defined set is exactly
    what the blueprint profiles currently emit, so anything else in the
    ``spatial_filter`` schema is stale. Mirrors
    ``services.scenario_canvas._purge_models_for_deleted_scenarios``.
    """
    from brewgis.sqlmesh.macros.spatial_filter_blueprints import (
        spatial_filter_model_fqns,
    )
    from brewgis.workspace.analysis.sqlmesh_runner import get_state_context
    from brewgis.workspace.analysis.sqlmesh_runner import normalize_fqn
    from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
    from brewgis.workspace.analysis.sqlmesh_runner import snapshot_name

    defined = {normalize_fqn(fqn) for fqn in spatial_filter_model_fqns()}
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


def refresh_spatial_filter_layer(layer: Layer) -> None:
    """Bring the spatial-filter models in line with the active spatial filters.

    Building or removing a filter changes which table *layer* draws from, and
    which projections other layers' conditions read — so the changed layer's
    model and every filter source it reads are planned together, and models the
    blueprints no longer define are dropped from the environments first (a stale
    snapshot fails the plan that would promote it). Mirrors
    ``views.base_canvas.SelectBaseCanvasForm.form_valid``'s fill toggle —
    plan/purge plus a Martin refresh.

    No-op under tests: the SQLMesh state schema belongs to the running stack,
    not to the test database a test process builds layers in.
    """
    from django.conf import settings

    from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
    from brewgis.workspace.services.tile_server import ensure_martin_source

    if settings.TESTING:
        return
    _purge_undefined_spatial_filter_models()
    if layer_has_active_spatial_filter(layer):
        select = [
            filter_model_fqn(layer.pk),
            *(
                filter_source_model_fqn(*source)
                for source in layer_filter_sources(layer)
            ),
        ]
        run_sqlmesh_plan(
            environment="prod",
            select=select,
            auto_apply=True,
            no_prompts=True,
        )
    if layer.workspace.tile_server_backend == "martin":
        ensure_martin_source(f"{SPATIAL_FILTER_SCHEMA}.{filter_model_table(layer.pk)}")
