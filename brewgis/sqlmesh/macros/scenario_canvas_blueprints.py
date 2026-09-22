"""Scenario canvas blueprint profiles — one model per ALTERNATIVE scenario.

Each ALTERNATIVE scenario owns a canvas view
(``scenario_<slug>.scenario_<slug>_canvas``) that LEFT JOINs its workspace's
base canvas table with the scenario's pivoted ``PaintedCanvas`` overrides
(``COALESCE(painted, base)``, copy-on-write). Django used to create that view
imperatively (``services.canvas_view_manager``), which made it a *dependent*
of the base canvas model — so every ``sqlmesh plan`` that rebuilt the base
CASCADE-dropped the view (``PostgresEngineAdapter.create_view`` drops the old
view with ``cascade=True``) with nothing to recreate it, leaving the map and
the tile servers reading a view that no longer existed.

Emitting the views as blueprinted SQLMesh models hands SQLMesh sole ownership:
they are recreated as downstreams of the base layer on every rebuild, and
Django never issues the DDL again.

Naming — why the model is not named after the view it creates: SQLMesh names a
model's physical object ``{schema}__{table}__{version}`` (see
``snapshot.definition.table_name``; the project uses the global
``SCHEMA_AND_TABLE`` convention, with no per-model override). For a model named
``scenario_<slug>.scenario_<slug>_canvas`` that is ``27 + 2 * len(slug) + 10``
characters — over Postgres' 63-character limit for any slug longer than 12
(``martin-auto-refresh-test`` produced an 86-character identifier and SQLMesh
refuses it outright). So each scenario's model lives at
``brewgis.scenario_canvas.canvas_<scenario_id>`` (short, and stable across slug
edits) and the model's ``on_virtual_update`` statement creates the
scenario-named view over it — see ``models/scenarios/scenario_canvas.py``.

``scenario_canvas_profiles()`` is the single source of truth for the
per-scenario blueprint facts and reads the live ``Scenario`` table, so the set
of blueprinted models always matches the database. It is a function rather
than a module-level constant for the reason documented in
``region_blueprints``: SQLMesh serializes module-level values into the macro's
``python_env`` with ``repr()`` and evaluates them standalone (``prepare_env``
-> bare ``eval(payload)``, no namespace, no Django), which cannot express the
result of a live query.
"""

from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp
from sqlmesh import macro

_logger = logging.getLogger(__name__)

# Schema holding the per-scenario models. The views the map and tile servers
# read are the scenario-named ones (see the module docstring); this schema is
# implementation detail and is excluded from the table catalog (see
# ``services.sqlmesh_tables._EXCLUDED_SCHEMAS``).
MODEL_SCHEMA = "scenario_canvas"


def scenario_canvas_profiles() -> list[dict[str, object]]:
    """Per-scenario blueprint facts for every ALTERNATIVE scenario.

    BASE scenarios are excluded — they have no paint overlay and resolve
    straight to the workspace's base table via ``Scenario.base_layer_source``.

    ``schema``/``view_name`` are the *scenario-named* view this model creates
    (raw identifiers, not pre-quoted: the values are emitted into the model's
    SQL statements, where SQLMesh quotes identifiers itself).

    ``base_model`` is the 3-part ``brewgis.<base_table>`` FQN the model body
    selects from: SQLMesh snapshot-resolves a bare model FQN in a rendered
    query, which is what makes the canvas view's ``data_hash`` change (and so
    the view get recreated) when the base layer's snapshot does.
    ``is_sqlmesh_base`` picks between that FQN and the raw external
    ``base_table`` (a legacy base living in ``public`` isn't managed by
    SQLMesh and is never CASCADE-dropped by a plan).

    ``all_columns`` is the base table's column list, read here — at model-load
    time — rather than inside the model's ``execute``. The view's SQL has to
    be fixed for the model's lifetime: SQLMesh infers the model's columns from
    the SQL it renders at load time and re-creates the view with that column
    list, while a ``plan`` apply runs *after* it has already CASCADE-dropped
    and is rebuilding the base (measured: the base's virtual view is gone at
    that point, so a live ``information_schema`` read returned zero columns
    and Postgres rejected the DDL with ``CREATE VIEW specifies more column
    names than columns``).

    Scenarios whose base table can't hold a canvas view are skipped — one
    ``Scenario`` row pointing at a table that isn't a base canvas (or no
    longer exists) must not make the whole project unloadable, since these
    profiles are part of every model load. The predicate is the same one the
    base-canvas picker uses (``sqlmesh_tables._required_base_canvas_columns``),
    and such a scenario's ``create_canvas_view`` raised before this change too.
    Duplicate ``schema.view_name`` pairs are also skipped (``scenario_<slug>``
    schemas aren't workspace-scoped, so two workspaces may claim the same view
    name) — deterministically, lowest scenario id first.
    """
    import django

    django.setup()

    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import ScenarioType
    from brewgis.workspace.services.canvas_view_manager import _fetch_base_columns
    from brewgis.workspace.services.sqlmesh_tables import _required_base_canvas_columns

    required = _required_base_canvas_columns()
    columns_by_base: dict[str, list[str]] = {}
    claimed_by_view: dict[tuple[str, str], int] = {}
    profiles: list[dict[str, object]] = []
    scenarios = (
        Scenario.objects.filter(scenario_type=ScenarioType.ALTERNATIVE)
        .select_related("workspace")
        .order_by("id")
    )
    for scenario in scenarios:
        base_table = scenario.workspace.base_table
        if base_table not in columns_by_base:
            columns_by_base[base_table] = _fetch_base_columns(base_table)[2]
        columns = columns_by_base[base_table]
        if not required.issubset(columns):
            _logger.warning(
                "Scenario %s (%s) has no canvas view model: base table %s is "
                "not a base canvas (missing %s)",
                scenario.pk,
                scenario.slug,
                base_table,
                sorted(required.difference(columns)),
            )
            continue

        view_key = (scenario.target_schema, f"scenario_{scenario.slug}_canvas")
        owner = claimed_by_view.setdefault(view_key, int(scenario.pk))
        if owner != int(scenario.pk):
            _logger.warning(
                "Scenario %s (%s) shares canvas view %s.%s with scenario %s — "
                "skipping (scenario schemas are not workspace-scoped)",
                scenario.pk,
                scenario.slug,
                *view_key,
                owner,
            )
            continue

        profiles.append(
            {
                "model_table": f"canvas_{scenario.pk}",
                "schema": scenario.target_schema,
                "view_name": f"scenario_{scenario.slug}_canvas",
                "scenario_id": int(scenario.pk),
                "base_table": base_table,
                "base_model": f"brewgis.{base_table}",
                "is_sqlmesh_base": int(not base_table.startswith("public.")),
                "all_columns": columns,
            }
        )
    return profiles


def _variable_sql(value: object) -> str:
    """Render one blueprint variable as SQL literal text.

    Every value here is a string, an int, or a list of column names — unlike
    ``region_blueprints`` there is no bare-identifier variable
    (``schema``/``view_name`` stay string literals; SQLMesh turns them into
    identifiers where they address objects).
    """
    if isinstance(value, list):
        return "ARRAY[" + ", ".join(_variable_sql(item) for item in value) + "]"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)  # int -> exact numeric literal text


@macro()
def scenario_canvas_blueprints(evaluator) -> list[exp.Expr]:
    """One blueprint entry per ALTERNATIVE scenario, from ``scenario_canvas_profiles()``.

    Unused by the blueprinted Python model (``models/scenarios/scenario_canvas.py``),
    which consumes ``scenario_canvas_profiles()`` as dicts directly — keeping
    the column list and the pivot's scenario id in their native Python types.
    Kept as the SQL-model counterpart so a ``scenario_canvas.sql`` model can be
    swapped in without re-deriving the profiles.
    """
    return [
        sqlglot.parse_one(
            "("
            + ", ".join(
                f"{name} := {_variable_sql(value)}"
                for name, value in profile.items()
            )
            + ")",
            into=exp.Tuple,
        )
        for profile in scenario_canvas_profiles()
    ]
