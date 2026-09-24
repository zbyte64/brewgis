"""Built-form fill blueprint profiles — one model per opted-in workspace.

A workspace whose ``Workspace.fill_built_form`` is on does not paint over its
``base_table`` directly: it reads a *derived* base layer in which every parcel
that has a built-form signal but no built-form attributes is assigned the
closest-matching :class:`~brewgis.workspace.built_forms.models.BuildingType`.
``Workspace.effective_base_table`` is the single place that resolves which of
the two is in effect.

This macro is the source of truth for that derived layer's identity and shape.
It emits one profile per opted-in workspace, consumed by the blueprinted Python
model ``models/base_canvas/built_form_fill.py``::

    {model_table: "fill_<workspace pk>",
     source_ref: "brewgis.<base_table>",
     built_form_table: "<db_schema>.built_forms",
     all_columns: [<base table's columns, in DB order>]}

The selected source is never modified — the model materializes a new table, and
only the five built-form columns (``built_form_key``, ``du``, ``pop``, ``hh``,
``emp``) can differ from the source's row for the same parcel.

Naming — why the model lives in ``built_form_fill`` rather than in the source's
own schema: the model's name must be derivable from the workspace alone (the
blueprint macro and ``Workspace.effective_base_table`` both compute it without
looking up the source), and SQLMesh names a model's physical object
``{schema}__{table}__{version}`` under the global ``SCHEMA_AND_TABLE``
convention, so a short fixed schema keeps ``built_form_fill__fill_<pk>__<hash>``
far inside Postgres' 63-character identifier limit for any pk. That schema is
excluded from the table catalog and the base-canvas picker
(``services.sqlmesh_tables._EXCLUDED_SCHEMAS``) — a workspace's fill output is
not itself an importable source.

``built_form_fill_profiles()`` reads the live database, so the set of
blueprinted models always matches the workspaces that have opted in. It is a
function rather than a module-level constant for the reason documented in
``region_blueprints``: SQLMesh serializes module-level values into a macro's
``python_env`` with ``repr()`` and evaluates them standalone
(``prepare_env`` -> bare ``eval(payload)``, no namespace, no Django), which
cannot express the result of a live query.
"""

from __future__ import annotations

import logging

from brewgis.sqlmesh.macros.scenario_canvas_blueprints import _summarize

_logger = logging.getLogger(__name__)

# Schema holding the per-workspace fill models.
MODEL_SCHEMA = "built_form_fill"


def built_form_fill_profiles() -> list[dict[str, object]]:
    """Per-workspace blueprint facts for every workspace with the fill enabled.

    ``source_ref`` is always a 3-part ``brewgis.<base_table>`` FQN: the base
    canvas picker only offers SQLMesh-managed tables, so the source is always a
    model, and the FQN is what gives the fill model a real dependency on it
    (SQLMesh snapshot-resolves a bare model FQN in a rendered query).

    ``all_columns`` is the source table's column list, read here — at model-load
    time — rather than inside the model's ``execute``, for the reason
    ``scenario_canvas_profiles`` documents: the SELECT is fixed for the model's
    lifetime, and a live ``information_schema`` read during a plan apply happens
    after the plan has CASCADE-dropped and is rebuilding that very table.

    A workspace whose ``base_table`` can't hold a fill (it is not a base canvas,
    or no longer exists) is skipped with one summary warning, mirroring
    ``scenario_canvas_profiles``: these profiles are part of every model load,
    so one broken workspace must not make the whole project unloadable.
    """
    import django

    django.setup()

    from brewgis.workspace.models import Workspace
    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.sqlmesh_tables import _required_base_canvas_columns

    required = _required_base_canvas_columns()
    skipped: list[str] = []
    profiles: list[dict[str, object]] = []
    for workspace in Workspace.objects.filter(fill_built_form=True).order_by("pk"):
        source = workspace.base_table
        columns = _fetch_base_columns(source)[2]
        if not required.issubset(columns):
            _logger.debug(
                "Workspace %s has no built-form fill model: base table %s is "
                "not a base canvas (missing %s)",
                workspace.pk,
                source,
                sorted(required.difference(columns)),
            )
            skipped.append(f"{workspace.pk} ({source})")
            continue

        profiles.append(
            {
                "model_table": f"fill_{workspace.pk}",
                "source_ref": f"brewgis.{source}",
                "built_form_table": f"{workspace.db_schema}.built_forms",
                "all_columns": columns,
            }
        )
    if skipped:
        _logger.warning(
            "Skipped %s workspace(s) with no built-form fill model: %s not a "
            "base canvas [%s]",
            len(skipped),
            len(skipped),
            _summarize(skipped),
        )
    return profiles
