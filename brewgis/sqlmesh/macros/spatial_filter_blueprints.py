"""Geospatial-filter blueprint profiles — the models a spatial filter needs.

A layer whose active :class:`~brewgis.workspace.models.LayerFilter` tree contains
a ``spatial`` node cannot be filtered client-side, so the filter materializes new
tables (``Layer.effective_source``). Two sets of models, from one traversal of the
active filters:

* one projection per **filter source** — the other layer a condition reads —
  consumed by ``models/spatial_filter/spatial_filter_source.py``::

      {source_model_table: "src_<digest>", source_ref: "brewgis.<schema>.<table>",
       source_geom: "<geometry column>", all_columns: [<columns, in DB order>]}

* one per **filtered layer**, consumed by
  ``models/spatial_filter/spatial_filter.py``::

      {model_table: "filter_<layer pk>", source_ref: "brewgis.<schema>.<table>",
       all_columns: [...], source_geom: "<geometry column>",
       spatial_filters: [<filter_json with its resolved filter_ref>, ...]}

The projection is what makes the layer model's join index-driven: ``filter_ref``
is a filter source's projection model, whose geometry column is already in the
region's local CRS behind a GiST index, so the layer's ``EXISTS`` probe is an
index probe instead of a per-row scan of a view. Each ``spatial_filters`` entry is
the stored condition plus that ``filter_ref`` — the stored ``filter_json`` itself
never carries it, because the client-side compiler reads the same tree.

``spatial_filter_profiles()`` and ``spatial_filter_source_profiles()`` read the
live database, so the set of blueprinted models always matches the layers that
have spatial filters and the tables they read. They are functions rather than
module-level constants for the reason documented in ``region_blueprints``:
SQLMesh serializes module-level values into a macro's ``python_env`` with
``repr()`` and evaluates them standalone (``prepare_env`` -> bare
``eval(payload)``, no namespace, no Django), which cannot express the result of a
live query.

Naming — why the models live in ``spatial_filter`` rather than in the source's
own schema: SQLMesh names a model's physical object
``{schema}__{table}__{version}`` under the global ``SCHEMA_AND_TABLE``
convention, so a short fixed schema keeps ``spatial_filter__filter_<pk>__<hash>``
and ``spatial_filter__src_<digest>__<hash>`` far inside Postgres'
63-character identifier limit. That schema is excluded from the table catalog
(``services.sqlmesh_tables._EXCLUDED_SCHEMAS``) — a derived copy is not itself an
importable source.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.sqlmesh.macros.scenario_canvas_blueprints import _summarize

_logger = logging.getLogger(__name__)

# Schema holding the per-layer and per-source spatial-filter models. Must match
# ``services.spatial_filter.SPATIAL_FILTER_SCHEMA`` — this module is imported
# while SQLMesh loads the project, before Django is configured, and importing
# that service package would execute ``brewgis.workspace.services.__init__``
# (which imports Django models). The models import this constant, so this is the
# name the FQNs and the layer's tile source are built from.
MODEL_SCHEMA = "spatial_filter"


def _source_profiles(
    sources: list[tuple[str, str, str]],
    *,
    skipped: list[str],
) -> list[dict[str, object]]:
    """Blueprint facts for each filter source in *sources*.

    A source whose columns cannot be read (the table was dropped, or it has no
    registered geometry) is appended to *skipped* instead of being emitted: a
    projection model over it could only fail the whole plan.
    """
    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.spatial_filter import filter_source_model_table
    from brewgis.workspace.services.spatial_filter import filter_source_ref
    from brewgis.workspace.services.spatial_filter import registered_geometry_column

    profiles: list[dict[str, object]] = []
    for schema, table, _ in sources:
        geometry = registered_geometry_column(schema, table)
        columns = _fetch_base_columns(f"{schema}.{table}")[2]
        if geometry is None or not columns:
            skipped.append(f"{schema}.{table} (filter source)")
            continue
        profiles.append(
            {
                # Not "model_table": SQLMesh keys a declared model by its name
                # text, so the projections and the filtered-layer models have to
                # spell their blueprint variable differently or the two files
                # collide on `brewgis.spatial_filter.@{...}` before expansion.
                "source_model_table": filter_source_model_table(
                    schema, table, geometry
                ),
                "source_ref": filter_source_ref(schema, table),
                "source_geom": geometry,
                "all_columns": columns,
            }
        )
    return profiles


def spatial_filter_source_profiles() -> list[dict[str, object]]:
    """One projection profile per distinct table the active spatial filters read.

    Ordered by source identity, so the model list is stable across loads.
    """
    import django

    django.setup()

    from brewgis.workspace.services.spatial_filter import all_filter_sources

    skipped: list[str] = []
    profiles = _source_profiles(all_filter_sources(), skipped=skipped)
    if skipped:
        _logger.warning(
            "Skipped %s spatial filter source(s) with no projection model [%s]",
            len(skipped),
            _summarize(skipped),
        )
    return profiles


def spatial_filter_profiles() -> list[dict[str, object]]:
    """Per-layer blueprint facts for every layer with an active spatial filter.

    Each ``spatial`` node in a layer's conditions is resolved to the projection
    model that carries its table's local-CRS geometry; a layer with a node whose
    source has no projection (see ``spatial_filter_source_profiles``) is skipped
    with one summary warning, so one broken source never makes the whole project
    unloadable — the same rule ``built_form_fill_profiles`` follows.

    ``all_columns`` is the layer's source table's column list, read here — at
    model-load time — rather than inside the model's ``execute``, for the reason
    ``scenario_canvas_profiles`` documents: the SELECT is fixed for the model's
    lifetime, and a live ``information_schema`` read during a plan apply happens
    after the plan has CASCADE-dropped and is rebuilding that very table.
    """
    import django

    django.setup()

    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.spatial_filter import FILTER_REF_KEY
    from brewgis.workspace.services.spatial_filter import filter_model_table
    from brewgis.workspace.services.spatial_filter import filter_source_model_fqn
    from brewgis.workspace.services.spatial_filter import filter_source_model_table
    from brewgis.workspace.services.spatial_filter import filter_source_of_node
    from brewgis.workspace.services.spatial_filter import geometry_column
    from brewgis.workspace.services.spatial_filter import source_ref_for_layer
    from brewgis.workspace.services.spatial_filter import spatial_nodes

    resolved = {
        str(profile["source_model_table"])
        for profile in spatial_filter_source_profiles()
    }
    skipped: list[str] = []
    profiles: list[dict[str, object]] = []
    for layer, nodes in spatial_nodes().items():
        where = f"{layer.pk} ({layer.db_schema or layer.workspace.db_schema}.{layer.db_table})"
        schema = layer.db_schema or layer.workspace.db_schema
        source_ref = source_ref_for_layer(schema, layer.db_table)
        if source_ref is None:
            skipped.append(where)
            continue
        spatial_filters: list[dict[str, Any]] = []
        for node in nodes:
            source = filter_source_of_node(node)
            if source is None or filter_source_model_table(*source) not in resolved:
                # No projection for this condition's table: a model over it could
                # only fail the plan, so the layer keeps its declared source.
                spatial_filters = []
                break
            spatial_filters.append(
                {**node, FILTER_REF_KEY: filter_source_model_fqn(*source)}
            )
        if not spatial_filters:
            skipped.append(where)
            continue
        profiles.append(
            {
                "model_table": filter_model_table(layer.pk),
                "source_ref": source_ref,
                "all_columns": _fetch_base_columns(f"{schema}.{layer.db_table}")[2],
                "source_geom": geometry_column(schema, layer.db_table),
                "spatial_filters": spatial_filters,
            }
        )
    if skipped:
        _logger.warning(
            "Skipped %s layer(s) with no spatial-filter model — source is not "
            "a SQLMesh-backed or external table, or a filter source has no "
            "projection [%s]",
            len(skipped),
            _summarize(skipped),
        )
    return profiles


def spatial_filter_model_fqns() -> list[str]:
    """FQNs of every model the spatial-filter blueprints currently define.

    The project's definition of "should exist" — the complement, in the
    ``spatial_filter`` schema, is what a refresh purges (see
    ``services.spatial_filter.refresh_spatial_filter_layer``).
    """
    from brewgis.workspace.services.spatial_filter import SPATIAL_FILTER_SCHEMA

    tables = [
        *(str(profile["model_table"]) for profile in spatial_filter_profiles()),
        *(
            str(profile["source_model_table"])
            for profile in spatial_filter_source_profiles()
        ),
    ]
    return [f'brewgis."{SPATIAL_FILTER_SCHEMA}"."{table}"' for table in tables]
