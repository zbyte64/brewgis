"""Analysis blueprint profiles — one instance of every analysis model per scenario.

The 28 models under ``models/analysis/`` used to be single models in the
``analysis`` schema whose per-scenario identity came from a SQLMesh *environment*
(``scenario_<id>`` + the default ``environment_suffix_target=SCHEMA``, which
landed their virtual views at ``analysis__scenario_<id>.<name>``) and whose
inputs came from plan-time ``variables`` (``parcel_table``, ``built_form_table``,
``base_canvas_table``, ``constraints``, ``canonical_*``). That made every
analysis run a whole SQLMesh environment and every per-run tunable a plan
argument Django had to thread through.

They now follow the scenario-canvas pattern: this macro emits one model
instance per scenario from the live ``Scenario`` table, so each scenario's
analysis models are first-class SQLMesh models with stable names, materialized
in ``prod``. Each model's ``on_virtual_update`` statement publishes its result
at the location the Layers/Martin/UI paths already read,
``analysis__scenario_<pk>.<model name>`` — so nothing downstream changes. The
per-run tunables (``constraints``, ``column_mapping``) are persisted on the
``Scenario`` (see ``workspace/models.py``) and baked into these blueprints.

Naming — why the model is not named after the view it publishes: SQLMesh names a
model's physical object ``{schema}__{table}__{version}`` (``SCHEMA_AND_TABLE``
convention, global, no per-model override) and the plan-time temp object appends
``_schema_tmp``; Postgres caps identifiers at 63 characters. With the model in
the result schema itself (``analysis__scenario_<pk>``, 19 + len(pk) characters)
the longest model (``displacement_risk_dynamic``, 25) would need
``20 + 2 + 25 + 2 + 10 + 11 = 70``. So each scenario's models live in
``brewgis.ascn<scenario_pk>`` (short, stable, and excluded from the table
catalog — see ``services.sqlmesh_tables._is_excluded_schema``) and their
``on_virtual_update`` statements create the result views over them. Worst case
with a 7-digit pk: ``11 + 2 + 25 + 2 + 10 + 11 = 61 <= 63`` ✓ — the binding
constraint is ``len(schema) + len(table) <= 38`` (kept: ``ascn<id>`` is
``4 + len(pk)``, so any pk up to 10 digits fits; a longer one is skipped by the
guard below rather than truncated).

``analysis_blueprint_profiles()`` reads the live database, so the set of
blueprinted models always matches the scenarios that have actually been
analyzed. It is a function rather than a module-level constant for the reason
documented in ``region_blueprints``: SQLMesh serializes module-level values into
the macro's ``python_env`` with ``repr()`` and evaluates them standalone
(``prepare_env`` -> bare ``eval(payload)``, no namespace, no Django), which
cannot express the result of a live query.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
from typing import Any

import sqlglot
from sqlglot import exp
from sqlmesh import macro

from brewgis.sqlmesh.model_names import MODEL_SCHEMA_PREFIX
from brewgis.sqlmesh.model_names import RESULT_SCHEMA_TEMPLATE

# A module-level logger would be walked into the macro's serialized python_env by
# SQLMesh (``serialize_env``) and cannot be repr'd — ``logging`` is referenced as
# a module instead, and the logger is looked up where it is used.
_LOGGER_NAME = __name__

# Profile keys whose value names an object rather than a literal, rendered as a
# bare identifier — the form ``region_blueprints`` uses for ``region`` (they are
# interpolated into object names, e.g. ``brewgis.@{scenario_schema}.<model>``,
# where a quoted literal would become part of the identifier). ``parcel_key_type``
# is a bare SQL *token* for the same reason: it is a Python model's column type
# (SQLMesh renders an ``@``-bearing column type per blueprint and parses the
# result, so a quoted literal would not parse as a type).
_IDENTIFIER_VARS = {
    "scenario_schema",
    "result_schema",
    "model_table",
    "parcel_key_type",
    "road_network_region",
}

# Postgres column type -> the type a model declares for the parcel key. The key
# is whatever the scenario's parcel source keys on, and the demo regions do not
# agree: the assessor APN is ``varchar`` while the legacy ``public.base_canvas``
# and ``sacog.base_canvas_reconciled`` key on a numeric id. A model that declares
# the wrong one cannot join the rest of its scenario's models (Postgres has no
# text = integer operator), so the type travels in the blueprint.
_PARCEL_KEY_TYPES = {
    "character varying": "TEXT",
    "text": "TEXT",
    "integer": "INT",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "numeric": "DOUBLE",
    "double precision": "DOUBLE",
    "real": "FLOAT",
}


def _parcel_key_type(base_table: str, column_mapping: dict[str, str]) -> str:
    """The SQL type *base_table* keys its parcels on, as a model column type.

    ``column_mapping`` is the scenario's canonical-name override: a scenario may
    take its parcel id from a source column named something else.

    Falls back to TEXT when the table or column is not found — the assessor APN
    is the common case, and a wrong guess is not silent: the model's first insert
    casts the key and fails.
    """
    from django.db import connection

    column = column_mapping.get("parcel_id", "parcel_id")
    schema, _, table = base_table.partition(".")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            [schema, table, column],
        )
        row = cursor.fetchone()
    if row is None:
        return "TEXT"
    return _PARCEL_KEY_TYPES.get(row[0], "TEXT")


def _canvas_model_fqns() -> dict[int, str]:
    """Per-scenario canvas model FQN, for the scenarios that have one.

    A scenario's parcel source is its canvas (base canvas + painted edits), read
    through the canvas *model* rather than the scenario-named view so the
    analysis models get a real SQLMesh dependency on it. The canvas model is not
    emitted for a scenario whose base table can't carry one (see
    ``scenario_canvas_profiles``), and a blueprint must never name a model that
    does not exist — so the analysis is skipped for exactly those scenarios.

    Imported inside the function (like the Django imports below): SQLMesh
    serializes every module-level object a macro's python_env references, and
    importing that module at module level drags its ``Logger`` in with it.
    """
    from brewgis.sqlmesh.macros.scenario_canvas_blueprints import MODEL_SCHEMA
    from brewgis.sqlmesh.macros.scenario_canvas_blueprints import (
        scenario_canvas_profiles,
    )

    return {
        int(profile["scenario_id"]): (
            f"brewgis.{MODEL_SCHEMA}.canvas_{profile['scenario_id']}"
        )
        for profile in scenario_canvas_profiles()
    }


def _drop_inherited_connection() -> None:
    """Drop the DB connection this process inherited from its parent, if any.

    These profiles are read while SQLMesh loads models, which it does in forked
    worker processes. A forked child inherits the parent's already-open
    connection — and the parent has normally used it: Django wraps every request
    in a transaction, and the pipeline records the ``AnalysisRun`` row before
    planning. Two processes sharing one Postgres connection corrupts its
    protocol state, which shows up as introspection returning *no columns* (a
    scenario silently loses its models) or as a read that never returns (a plan
    that never loads).

    Dropping it is *not* simply ``connections.close_all()``: closing sends a
    Terminate message over the socket this process shares with its parent, which
    ends the parent's server-side session. The parent is still using that
    connection — it keeps loading models, planning and writing result rows after
    the fork — so the damage surfaces there, as
    ``OperationalError: server closed the connection unexpectedly`` while it
    loads the *next* model file. Closing this process's copy of the socket's
    file descriptor first (which the server never hears about) leaves libpq
    unable to write that Terminate, and the parent's own copy keeps the session
    alive. The child then opens a fresh connection for its own reads.

    The transaction flags are cleared before the close because a fork can land
    inside the parent's atomic block, and ``close()`` would then leave the
    wrapper reporting a connection it has already closed.

    The check is deliberately "am I a fork?" rather than "am I in a
    transaction?" — the parent is in one for every request, and a child must
    still drop the connection it inherited from it.
    """
    if multiprocessing.parent_process() is None:
        return  # not a fork — leave this process's own connection alone

    import contextlib
    import os

    from django.db import connections

    for alias in connections:
        wrapper = connections[alias]
        wrapper.in_atomic_block = False
        wrapper.needs_rollback = False
        wrapper.closed_in_transaction = False
        wrapper.savepoint_ids = []
        # The parent's post-commit hooks belong to the parent, not to this
        # child, which must not replay them.
        wrapper.run_on_commit = []

        inherited = wrapper.connection
        if inherited is None:
            continue
        with contextlib.suppress(OSError):
            # Already closed, or a driver connection without a socket.
            os.close(inherited.fileno())

    connections.close_all()


def _scenario_profiles() -> list[dict[str, Any]]:
    """Per-scenario analysis blueprint facts, minus the model being blueprinted.

    Only scenarios that have at least one ``AnalysisRun`` (any status) are
    emitted: a scenario that has never been analyzed has no result views to
    publish, and emitting all of them would multiply the project's model count
    for nothing. The run row is created *before* the plan loads models (see
    ``analysis.pipeline``), so a first launch still finds its profiles.

    ``scenario_id`` is the scenario *slug* (the identifier the result tables used
    to carry, e.g. in preprocessor-written names such as
    ``food_access_inputs_<slug>``); ``scenario_pk`` is the primary key and what
    the model/result schema names are built from. Do not use the slug for those:
    a slug may contain hyphens, which are not valid in an unquoted identifier.

    ``parcel_table``/``built_form_table``/``base_canvas_table`` are string
    literals (the ``@ref_model`` call in the model bodies needs a ``str``), and
    ``parcel_table`` is ``None`` when the scenario has no SQLMesh-backed parcel
    source at all — such a scenario is skipped with a warning (mirroring
    ``scenario_canvas_profiles``): one unplannable scenario must not make the
    whole project unloadable, since these profiles are part of every model load.
    """
    import django

    django.setup()

    from brewgis.workspace.models import AnalysisRun
    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import ScenarioType
    from brewgis.workspace.services.fetch_clone import region_for_base_table
    from brewgis.workspace.services.fetch_clone import road_network_region

    _drop_inherited_connection()

    scenario_ids = set(
        AnalysisRun.objects.values_list("scenario_id", flat=True).distinct()
    )
    canvas_fqns: dict[int, str] | None = None
    profiles: list[dict[str, Any]] = []
    scenarios = (
        Scenario.objects.filter(pk__in=scenario_ids)
        .select_related("workspace")
        .order_by("pk")
    )
    for scenario in scenarios:
        workspace = scenario.workspace
        base_table = workspace.base_table
        if scenario.scenario_type == ScenarioType.ALTERNATIVE:
            # ``canvas_<pk>`` is the ALTERNATIVE scenario's painted-features
            # model (base canvas + PaintedCanvas overlay, COALESCEd).
            if canvas_fqns is None:
                canvas_fqns = _canvas_model_fqns()
            parcel_table = canvas_fqns.get(int(scenario.pk))
        elif not base_table.startswith("public."):
            # A base canvas managed by SQLMesh: reference it as a model FQN so
            # the analysis depends on it (a ``public.`` table is not a model).
            parcel_table = f"brewgis.{base_table}"
        else:
            parcel_table = None

        if parcel_table is None:
            logging.getLogger(_LOGGER_NAME).warning(
                "Scenario %s (%s) has no analysis models: no SQLMesh-backed "
                "parcel source (workspace base table %s is not managed by "
                "SQLMesh, or the scenario has no canvas model)",
                scenario.pk,
                scenario.slug,
                base_table,
            )
            continue

        profile: dict[str, Any] = {
            "scenario_pk": int(scenario.pk),
            "scenario_id": scenario.slug,
            "scenario_schema": f"{MODEL_SCHEMA_PREFIX}{scenario.pk}",
            "result_schema": RESULT_SCHEMA_TEMPLATE.format(pk=scenario.pk),
            "parcel_table": parcel_table,
            "parcel_key_type": _parcel_key_type(
                base_table, scenario.column_mapping or {}
            ),
            "built_form_table": f"{workspace.db_schema}.built_forms",
            "base_canvas_table": base_table,
            "constraints": scenario.constraints,
            # The region road network network_zone_distance routes over, and
            # whether that region really is the workspace's (see
            # ``fetch_clone.road_network_region``).
            "road_network_region": road_network_region(base_table),
            "road_network_available": region_for_base_table(base_table) is not None,
        }
        profile.update(
            {
                f"canonical_{name}": column
                for name, column in (scenario.column_mapping or {}).items()
            }
        )
        # Every analysis parameter is baked into every blueprint, so a
        # blueprinted model resolves it without a config var or a plan-time
        # variable — rematerialization (which re-renders from these profiles
        # alone) keeps the scenario's own values. Imported inside the function
        # for the same reason as the Django imports above: SQLMesh serializes
        # the module-level objects a macro's python_env references.
        from brewgis.workspace.analysis.module_registry import ANALYSIS_PARAMETERS

        overrides = scenario.analysis_params or {}
        for param in ANALYSIS_PARAMETERS:
            profile[param.name] = overrides.get(param.name, param.default)
        profiles.append(profile)
    return profiles


def analyzed_scenario_ids() -> set[int]:
    """Primary keys of the scenarios that have analysis models.

    The scenarios a plan must be able to load models for — used by the
    scenario-analysis lifecycle to tell a live scenario from a deleted one
    (see ``workspace/services/scenario_analysis.py``).
    """
    return {int(profile["scenario_pk"]) for profile in _scenario_profiles()}


def analysis_blueprint_profiles(model_name: str) -> list[dict[str, Any]]:
    """Per-scenario blueprint facts for the analysis model *model_name*."""
    return [dict(profile, model_table=model_name) for profile in _scenario_profiles()]


def _variable_sql(name: str, value: object) -> str:
    """Render one blueprint variable as the SQL literal text it originally had.

    ``str`` becomes a quoted string literal, ``int`` an exact integer literal,
    and object names (``_IDENTIFIER_VARS``) a bare identifier.

    Note the two ways a blueprint variable can be *referenced*, which is what
    this text has to survive:

    - ``@{name}`` splices this text into the query as a bare *identifier*, so it
      only fits values that name an object (a schema, a table, a column) —
      ``_IDENTIFIER_VARS``, and the analysis parameters of the identifier kind.
    - ``@blueprint_var('name')`` re-parses this text as a SQL expression, which
      is what every *value* parameter uses: it is what makes ``0.85`` a numeric
      literal rather than the quoted identifier ``"0.85"``.

    ``list``/``dict`` values (``constraints`` is a list of
    ``{table, discount_pct, geom_col}`` objects) render as a *JSON string
    literal* rather than ``ARRAY[...]``: an array has no element type that can
    hold a heterogeneous record, and the array form would not parse — which
    would break the whole model load, since the rendered blueprint text is
    parsed before each model is created.
    """
    if name in _IDENTIFIER_VARS:
        return str(value)  # identifier, not a string literal
    if isinstance(value, bool):
        # Checked before the numeric fallback: ``str(False)`` is "False", which
        # is not a SQL boolean literal and would fail to parse.
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (list, dict)):
        return "'" + json.dumps(value).replace("'", "''") + "'"
    return str(value)  # int -> exact numeric literal text


@macro()
def analysis_blueprints(evaluator, model_name: str) -> list[exp.Expr]:
    """One blueprint entry per analyzed scenario, for analysis model *model_name*.

    Called from a model's ``MODEL (...)`` block as
    ``blueprints @analysis_blueprints('core_end_state')`` — the argument is the
    model's own bare name, which becomes its blueprint's ``model_table`` and so
    the name of the result view published over it.

    The profiles are returned inside **one** enclosing tuple, and that matters:
    SQLMesh reads a macro's rendered result as a list of expressions and only
    wraps a *multi-element* list itself (``if len(rendered_blueprints) > 1``),
    then treats whatever is left as the blueprints. A bare list of one profile
    therefore degenerates — the loader sees that profile's individual
    ``name := value`` pairs as blueprints, giving one model per *variable*,
    each named ``brewgis.public.@{model_table}`` (``scenario_schema`` falls back
    to the config default, ``model_table`` stays unrendered) and colliding with
    every other analysis model: "Duplicate SQL model name". Wrapping makes the
    shape identical for one scenario and for many.
    """
    profiles = [
        sqlglot.parse_one(
            "("
            + ", ".join(
                f"{name} := {_variable_sql(name, value)}"
                for name, value in profile.items()
            )
            + ")",
            into=exp.Tuple,
        )
        for profile in analysis_blueprint_profiles(model_name)
    ]
    return [exp.Tuple(expressions=profiles)]
