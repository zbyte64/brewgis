"""Analysis result lifecycle — the SQLMesh side of a scenario's analysis models.

A scenario's analysis models are blueprinted per scenario (see
``sqlmesh/macros/analysis_blueprints.py``): one SQLMesh model per analysis model
per analyzed scenario, living in the internal ``ascn<scenario_pk>`` schema, each
publishing its result view at ``analysis__scenario_<pk>.<model name>`` — the
location the Layers panel, the tile servers and the UI read. This module is what
Django calls to keep that arrangement consistent with the ``Scenario`` table:

- :func:`scenario_analysis_fqns` — the models a scenario owns.
- :func:`drop_scenario_analysis` — drop a deleted scenario's result schema and
  de-list its models from SQLMesh's environments, so a later plan can't trip
  over a snapshot whose models no longer exist.
- :func:`reconcile_scenario_analyses` — the repair pass: de-list models whose
  scenario is gone, then restate every live scenario's models so their result
  views are rebuilt if a plan promoted them without publishing the views.
"""

from __future__ import annotations

import logging

from django.db import connection

from brewgis.sqlmesh.model_names import MODEL_SCHEMA_PREFIX
from brewgis.workspace.analysis import module_registry
from brewgis.workspace.analysis.sqlmesh_runner import get_state_context
from brewgis.workspace.analysis.sqlmesh_runner import model_fqns_built_in
from brewgis.workspace.analysis.sqlmesh_runner import normalize_fqn
from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.analysis.sqlmesh_runner import snapshot_name
from brewgis.workspace.services.canvas_view_manager import _qi

logger = logging.getLogger(__name__)


def scenario_analysis_fqns(scenario_pk: int) -> list[str]:
    """SQLMesh FQNs of every analysis model *scenario_pk* owns."""
    return [
        module_registry.model_fqn(model_name, scenario_pk)
        for model_names in module_registry.MODULE_SQLMESH_SELECTORS.values()
        for model_name in model_names
    ]


def result_view_qualifier(scenario_pk: int, model_name: str) -> str:
    """Return the ``schema.view_name`` a scenario's analysis result is read at."""
    return f"{module_registry.result_schema_name(scenario_pk)}.{model_name}"


def drop_scenario_analysis(scenario_pk: int) -> None:
    """Drop *scenario_pk*'s result views and de-list its analysis models.

    Everything a scenario's analysis produces lives in its own
    ``analysis__scenario_<pk>`` schema, so dropping the schema takes every
    result view with it — no per-model bookkeeping to drift out of date.

    Deleting the scenario removes its models from the blueprint profiles, but
    SQLMesh's stored environments would still list those snapshots — and a later
    plan that promotes such a stale entry points it at a physical object it
    never creates, failing the whole plan. So they are removed from every
    environment here, before any plan can trip over them.
    """
    schema = module_registry.result_schema_name(scenario_pk)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE")
    purge_models_from_environments(scenario_analysis_fqns(scenario_pk))
    logger.info("Dropped analysis result schema %s", schema)


def modeled_scenario_ids() -> set[int]:
    """Scenario pks SQLMesh has analysis models for.

    The blueprint profiles skip a scenario with no SQLMesh-backed parcel source
    (see ``analysis_blueprint_profiles``): it has no models at all, so it must
    not be planned — nor reported as stale.
    """
    from brewgis.sqlmesh.macros.analysis_blueprints import analyzed_scenario_ids

    return analyzed_scenario_ids()


def reconcile_scenario_analyses() -> None:
    """Rebuild every analyzed scenario's result views from its current models.

    Planning the models is not enough to repair a stale one: when a plan
    promoted a model without publishing its result view, SQLMesh's state still
    believes that view is deployed, so a plain plan sees nothing to do.
    Restating the models forces each result view to be recreated over the
    model's current prod virtual view, which repairs a missing view and one
    still pointing at a superseded object alike.

    Models whose scenario no longer exists (or no longer has an ``AnalysisRun``)
    are de-listed first: they are no longer in the project, so a plan that
    promoted such an entry would fail.
    """
    modeled = modeled_scenario_ids()
    fqns = [fqn for pk in sorted(modeled) for fqn in scenario_analysis_fqns(pk)]
    _purge_models_for_unmodeled_scenarios(modeled)
    if not fqns:
        return

    # Only models a plan can actually restate: a scenario that has never been
    # planned has nothing to repair yet, and restating a model SQLMesh has never
    # built fails the whole pass.
    restate = model_fqns_built_in("prod", fqns)
    if not restate:
        logger.info("No analysis models built in prod yet — nothing to reconcile")
        return

    logger.info(
        "Reconciling %d analysis model(s) across %d scenario(s)",
        len(restate),
        len(modeled),
    )
    run_sqlmesh_plan(
        environment="prod",
        select=fqns,
        restate_models=restate,
        auto_apply=True,
        no_prompts=True,
    )


def _purge_models_for_unmodeled_scenarios(modeled: set[int]) -> list[str]:
    """De-list analysis models whose scenario is no longer analyzed.

    ``drop_scenario_analysis`` removes a deleted scenario's models, but this
    heals any that predate it (a scenario that lost its last ``AnalysisRun``, or
    one deleted before this lifecycle existed).
    """
    stale: list[str] = []
    for environment in get_state_context().state_sync.get_environments():
        stale.extend(
            name
            for name in (snapshot_name(entry) for entry in environment.snapshots_)
            if _is_stale_analysis_model(name, modeled)
        )
    if not stale:
        return []
    return purge_models_from_environments(stale)


def _is_stale_analysis_model(name: str, modeled: set[int]) -> bool:
    """Whether *name* (a snapshot name, quotes and all) is a model whose
    scenario has no models."""
    unquoted = normalize_fqn(name)
    prefix = f"brewgis.{MODEL_SCHEMA_PREFIX}"
    if not unquoted.startswith(prefix):
        return False
    raw_id = unquoted[len(prefix) :].split(".", 1)[0]
    return not raw_id.isdigit() or int(raw_id) not in modeled
