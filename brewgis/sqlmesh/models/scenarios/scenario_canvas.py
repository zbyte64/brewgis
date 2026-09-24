"""Scenario canvas view — Python SQL model (blueprinted, one per scenario).

Gives every ALTERNATIVE scenario's painted-features canvas view to SQLMesh, so
the view is created when the scenario is created and recreated as a downstream
whenever the workspace's base canvas model changes. Before this, Django created
the view imperatively and any ``sqlmesh plan`` rebuilding the base layer
CASCADE-dropped it with nothing to bring it back (the map and tile servers then
read a view that no longer existed).

One model per ALTERNATIVE scenario, resolved while SQLMesh imports this module.
With none in the database there is nothing to instantiate and the module
registers no model at all — see :mod:`brewgis.sqlmesh.blueprint_models` for why
an empty list cannot be handed to ``@model`` instead.

A plan only recreates these models if they are inside its selection: promotion
updates the virtual layer for every snapshot in the environment, but a
selection that excludes them (an upstream-only ``--select-model '+<base>'``)
leaves the view pointing at a physical object the plan never created. Rebuild a
base canvas with a trailing ``+`` (``make plan-base BASE=<fqn>``) and run
``manage.py reconcile_scenario_canvases`` if a plan was run without it.

Two SQLMesh constraints shape the definition:

- The model is *not* named after the view it creates. SQLMesh's physical object
  name is ``{schema}__{table}__{version}`` (`SCHEMA_AND_TABLE` convention,
  global config, no per-model override), which for a model named
  ``scenario_<slug>.scenario_<slug>_canvas`` exceeds Postgres' 63-character
  identifier limit once the slug is longer than 12 characters. So the model
  lives at ``brewgis.scenario_canvas.canvas_<scenario_id>`` and its
  ``on_virtual_update`` statement creates the scenario-named view over it —
  that statement runs inside the promotion transaction, right after the
  model's own virtual view exists.
- The SELECT is built from a column list resolved at *load* time (a blueprint
  value), never by querying the database while the model executes. See
  ``scenario_canvas_profiles`` for the measurement that forced this.

The SELECT itself comes from
:func:`brewgis.workspace.services.canvas_view_manager.build_canvas_view_select`
— the same generator the Django paint surfaces use for their column metadata —
so the COALESCE pivot is defined exactly once. It selects from a bare
``brewgis.<base_table>`` FQN, which SQLMesh snapshot-resolves when rendering
the query; that is what gives this model a real dependency on the base layer
without an explicit ``depends_on``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.blueprint_models import register_blueprint_model
from brewgis.sqlmesh.macros.scenario_canvas_blueprints import MODEL_SCHEMA
from brewgis.sqlmesh.macros.scenario_canvas_blueprints import scenario_canvas_profiles

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# Resolved when SQLMesh imports this module (i.e. while loading the project) —
# one entry per ALTERNATIVE scenario in the database at that moment.
_PROFILES = scenario_canvas_profiles()

# The scenario-named view each model creates, pointing at the model's *prod*
# virtual view (``scenario_canvas.<table>``) rather than at ``@this_model``:
# this statement also runs when a non-prod environment is promoted, and the map
# reads the same scenario-named view in every environment.
_ON_VIRTUAL_UPDATE = [
    'CREATE SCHEMA IF NOT EXISTS "@{schema}"',
    (
        'CREATE OR REPLACE VIEW "@{schema}"."@{view_name}" AS '
        f'SELECT * FROM {MODEL_SCHEMA}."@{{model_table}}"'
    ),
]


# One declaration, applied once per ALTERNATIVE scenario below: with none in the
# database there is nothing to instantiate.
_CANVAS_MODEL = model(
    name=f"brewgis.{MODEL_SCHEMA}.@{{model_table}}",
    kind=ModelKindName.VIEW,
    description=(
        "One ALTERNATIVE scenario's painted canvas: the workspace base canvas"
        " LEFT JOIN its PaintedCanvas overrides (COALESCE(painted, base),"
        " copy-on-write), one row per parcel."
    ),
    blueprints=[dict(profile) for profile in _PROFILES],
    on_virtual_update=_ON_VIRTUAL_UPDATE,
    is_sql=True,
)


def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the scenario's canvas SELECT body.

    The returned string is not macro-rendered again by SQLMesh, so blueprint
    variables are resolved here through the evaluator.

    No ``columns`` declaration — the SELECT is built from the base table's
    column list captured in the blueprint, which SQLMesh infers columns from.
    For the same reason there is no ``depends_on``: the
    ``FROM brewgis.<base_table>`` the generator emits establishes the edge.

    No ``column_descriptions`` either, for that same reason: the column set is
    the per-scenario base table's, so a static dict would name columns that
    another scenario's base table does not have (each name it misses is a
    ``COMMENT ON COLUMN`` SQLMesh logs a warning for). The SQLMesh UI infers
    them through lineage from the base canvas model instead.
    """
    from brewgis.workspace.services.canvas_view_manager import build_canvas_view_select

    base_table = str(evaluator.blueprint_var("base_table"))
    is_sqlmesh_base = int(evaluator.blueprint_var("is_sqlmesh_base", 1))
    scenario_id = int(evaluator.blueprint_var("scenario_id"))
    all_columns = [str(column) for column in evaluator.blueprint_var("all_columns", [])]
    base_ref = (
        str(evaluator.blueprint_var("base_model")) if is_sqlmesh_base else base_table
    )

    return build_canvas_view_select(
        base_ref=base_ref,
        all_columns=all_columns,
        scenario_id=scenario_id,
    )


# One model per ALTERNATIVE scenario: with none in the database, registering
# nothing is what keeps an empty blueprint list from becoming a phantom model.
execute = register_blueprint_model(_CANVAS_MODEL, execute, _PROFILES)
