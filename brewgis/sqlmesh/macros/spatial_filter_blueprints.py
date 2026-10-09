"""Layer-filter blueprint profiles — the models an applied filter needs.

Applying a :class:`~brewgis.workspace.models.LayerFilter` materializes its
matching rows as a new table that a new Layer draws (``services.spatial_filter``).
Two sets of models, from one traversal of the applied filters:

* one projection per **filter source** — the other layer a spatial condition
  reads — consumed by ``models/spatial_filter/spatial_filter_source.py``::

      {source_model_table: "src_<digest>", source_ref: "brewgis.<schema>.<table>",
       source_geom: "<geometry column>", all_columns: [<columns, in DB order>]}

* one per **applied filter**, consumed by
  ``models/spatial_filter/spatial_filter.py``::

      {model_table: "filter_<filter pk>", source_ref: "brewgis.<schema>.<table>",
       all_columns: [...], source_geom: "<geometry column>",
       filter_json: <the filter's tree, spatial nodes carrying their filter_ref>}

The projection is what makes a spatial condition index-driven: ``filter_ref`` is
a filter source's projection model, whose geometry column is already in the
region's local CRS behind a GiST index, so the filter's ``EXISTS`` probe is an
index probe instead of a per-row scan of a view. The stored ``filter_json``
itself never carries it, because the editor and the preview compiler read the
same tree.

``spatial_filter_profiles()`` and ``spatial_filter_source_profiles()`` read the
live database, so the set of blueprinted models always matches the applied
filters and the tables they read. They are functions rather than module-level
constants for the reason documented in ``region_blueprints``: SQLMesh serializes
module-level values into a macro's ``python_env`` with ``repr()`` and evaluates
them standalone (``prepare_env`` -> bare ``eval(payload)``, no namespace, no
Django), which cannot express the result of a live query.

Naming — why the models live in ``spatial_filter`` rather than in the source's
own schema: SQLMesh names a model's physical object
``{schema}__{table}__{version}`` under the global ``SCHEMA_AND_TABLE``
convention, so a short fixed schema keeps ``spatial_filter__filter_<pk>__<hash>``
and ``spatial_filter__src_<digest>__<hash>`` far inside Postgres'
63-character identifier limit. That schema is excluded from the table catalog
(``services.sqlmesh_tables._EXCLUDED_SCHEMAS``) — a filtered layer is reached
through its own Layer, never imported as a source.
"""

from __future__ import annotations

import logging

from brewgis.sqlmesh.macros.scenario_canvas_blueprints import _summarize

_logger = logging.getLogger(__name__)

# Schema holding the per-filter and per-source models. Must match
# ``services.spatial_filter.SPATIAL_FILTER_SCHEMA`` — this module is imported
# while SQLMesh loads the project, before Django is configured, and importing
# that service package would execute ``brewgis.workspace.services.__init__``
# (which imports Django models). The models import this constant, so this is the
# name the FQNs and the filtered layer's table are built from.
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
    from brewgis.workspace.services.spatial_filter import registered_geometry_column
    from brewgis.workspace.services.spatial_filter import table_ref

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
                "source_ref": table_ref(schema, table),
                "source_geom": geometry,
                "all_columns": columns,
            }
        )
    return profiles


def spatial_filter_source_profiles() -> list[dict[str, object]]:
    """One projection profile per distinct table the applied filters read.

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
    """Per-filter blueprint facts for every applied filter.

    Each ``spatial`` node in a filter's tree is resolved to the projection model
    that carries its table's local-CRS geometry; a filter with a node whose
    source has no projection (see ``spatial_filter_source_profiles``), or whose
    layer's table has no readable columns, is skipped with one summary warning,
    so one broken filter never makes the whole project unloadable — the same
    rule ``built_form_fill_profiles`` follows. Applying such a filter fails
    loudly instead (``services.spatial_filter.refresh_filter_models``).

    ``all_columns`` is the filtered layer's table's column list, read here — at
    model-load time — rather than inside the model's ``execute``, for the reason
    ``scenario_canvas_profiles`` documents: the SELECT is fixed for the model's
    lifetime, and a live ``information_schema`` read during a plan apply happens
    after the plan has CASCADE-dropped and is rebuilding that very table.
    """
    import django

    django.setup()

    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.spatial_filter import applied_filters
    from brewgis.workspace.services.spatial_filter import filter_model_table
    from brewgis.workspace.services.spatial_filter import geometry_column
    from brewgis.workspace.services.spatial_filter import table_ref
    from brewgis.workspace.services.spatial_filter import with_filter_refs

    resolved = {
        str(profile["source_model_table"])
        for profile in spatial_filter_source_profiles()
    }
    skipped: list[str] = []
    profiles: list[dict[str, object]] = []
    for flt in applied_filters():
        schema, table = flt.layer.source_table()
        columns = _fetch_base_columns(f"{schema}.{table}")[2]
        tree = with_filter_refs(flt.filter_json, resolved)
        if not columns or tree is None:
            skipped.append(f"{flt.pk} ({schema}.{table})")
            continue
        profiles.append(
            {
                "model_table": filter_model_table(flt.pk),
                "source_ref": table_ref(schema, table),
                "all_columns": columns,
                "source_geom": geometry_column(schema, table),
                "filter_json": tree,
            }
        )
    if skipped:
        _logger.warning(
            "Skipped %s applied filter(s) with no model — the filtered layer's "
            "table has no readable columns, or a filter source has no "
            "projection [%s]",
            len(skipped),
            _summarize(skipped),
        )
    return profiles


def spatial_filter_model_fqns() -> list[str]:
    """FQNs of every model the filter blueprints currently define.

    The project's definition of "should exist" — the complement, in the
    ``spatial_filter`` schema, is what a refresh purges (see
    ``services.spatial_filter.refresh_filter_models``).
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
