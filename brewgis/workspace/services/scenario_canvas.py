"""Scenario canvas view lifecycle — the SQLMesh side of a scenario's canvas.

A scenario's canvas view (``scenario_<slug>.scenario_<slug>_canvas``) is a
SQLMesh object: the blueprinted model in
``sqlmesh/models/scenarios/scenario_canvas.py`` recreates it whenever the
workspace's base canvas model is rebuilt. This module is what Django calls to
bring a scenario's canvas into existence, to clean it up, and to keep the tile
server from serving stale tiles for it:

- :func:`materialize_scenario_canvas` — plan the scenario's model (creating the
  view, and registering the model so later base-layer plans recreate it).
- :func:`drop_scenario_canvas` — drop the view and the scenario's schema when
  the scenario itself is deleted. The model leaves the project on the next plan
  (the blueprint profiles no longer emit it).
- :func:`purge_scenario_canvas_tiles` — drop the tile server's cached tiles for
  the view. Paint writes do *not* need any view recreation: the canvas is a live
  view over ``workspace_paintedcanvas``, so only the cache can be stale.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import DatabaseError
from django.db import connection
from django.db import transaction

from brewgis.workspace.analysis.sqlmesh_runner import normalize_fqn
from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.analysis.sqlmesh_runner import snapshot_name
from brewgis.workspace.services.canvas_view_manager import _qi
from brewgis.workspace.services.tile_server import purge_martin_cache

if TYPE_CHECKING:
    from collections.abc import Iterable

    from brewgis.workspace.models import Scenario

logger = logging.getLogger(__name__)


def canvas_view_qualifier(scenario: Scenario) -> str:
    """Return the ``schema.view_name`` the map and tile servers read."""
    return f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"


def canvas_model_selector(scenario: Scenario) -> str:
    """Return the SQLMesh selector for *scenario*'s canvas model.

    Identifier parts are double-quoted so a hyphenated slug (or schema)
    survives selector parsing.
    """
    return canvas_model_fqn(scenario)


def materialize_scenario_canvas(scenario: Scenario) -> None:
    """Create (or refresh) one scenario's canvas view via its SQLMesh model."""
    materialize_scenario_canvases([scenario])


def materialize_scenario_canvases(scenarios: Iterable[Scenario]) -> None:
    """Create (or refresh) several scenarios' canvas views in a single plan.

    Planning is synchronous — the caller (scenario creation) needs the view to
    exist before the map is opened — and one plan covers every scenario at
    once, so a reconciliation pass costs one plan rather than one per scenario.

    ``environment="prod"`` because the logical view name is environment-free:
    the scenario-named view always shows the promoted data.
    """
    selected = list(scenarios)
    if not selected:
        return

    run_sqlmesh_plan(
        environment="prod",
        select=[canvas_model_selector(scenario) for scenario in selected],
        auto_apply=True,
        no_prompts=True,
    )
    logger.info(
        "Materialized canvas view(s) for scenario(s) %s",
        [scenario.pk for scenario in selected],
    )


def canvas_view_is_healthy(scenario: Scenario) -> bool:
    """Return whether *scenario*'s canvas view exists and can be queried.

    Used for reporting: the realistic failure is a view that is *gone* (a plan
    dropped it with ``CASCADE`` and did not recreate it). A view that still
    exists but targets a superseded object is not detectable this way — and
    PostgreSQL keeps view dependencies consistent, so a surviving view whose
    target vanished only happens through a rename, which PostgreSQL tracks too.

    The probe is wrapped in its own transaction block so a failed statement
    rolls back before the error is handled — PostgreSQL aborts the whole
    transaction otherwise (including an enclosing one).
    """
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 FROM {_qi(canvas_view_qualifier(scenario))} LIMIT 0"
            )
    except DatabaseError:
        return False
    return True


def _modeled_scenario_ids() -> set[int]:
    """Scenario ids SQLMesh has a canvas model for.

    The blueprint profiles skip a scenario whose base table can't carry a
    canvas view (see ``scenario_canvas_profiles``): no view is ever created for
    it, so it must not be planned — nor reported as broken.
    """
    from brewgis.sqlmesh.macros.scenario_canvas_blueprints import (
        scenario_canvas_profiles,
    )

    return {int(profile["scenario_id"]) for profile in scenario_canvas_profiles()}


def _purge_models_for_deleted_scenarios(modeled: set[int]) -> list[str]:
    """De-list canvas models whose scenario no longer exists.

    A scenario deleted while its model was already planned leaves a snapshot in
    the environments (``drop_scenario_canvas`` removes it, but this heals any
    that predate that). A plan that promotes such an entry fails — it points
    the view at a physical object the plan never creates.
    """
    from brewgis.workspace.analysis.sqlmesh_runner import get_state_context

    stale: list[str] = []
    for environment in get_state_context().state_sync.get_environments():
        stale.extend(
            name
            for name in (snapshot_name(entry) for entry in environment.snapshots_)
            if _is_stale_canvas_model(name, modeled)
        )
    if not stale:
        return []
    return purge_models_from_environments(stale)


def _is_stale_canvas_model(name: str, modeled: set[int]) -> bool:
    """Whether *name* (a snapshot name, quotes and all) is a canvas model whose
    scenario is gone."""
    from brewgis.sqlmesh.macros.scenario_canvas_blueprints import MODEL_SCHEMA

    unquoted = normalize_fqn(name)
    prefix = f"brewgis.{MODEL_SCHEMA}."
    if not unquoted.startswith(prefix):
        return False
    raw_id = unquoted[len(prefix) :].split(".", 1)[0].rsplit("_", 1)[-1]
    return raw_id.isdigit() and int(raw_id) not in modeled


def reconcile_scenario_canvases() -> list[int]:
    """Recreate every ALTERNATIVE scenario's canvas view from its current base.

    Planning the canvas models is not enough to repair a stale one: when a plan
    promoted a canvas model without recreating its view, SQLMesh's state still
    believes that view is deployed, so a plain plan sees nothing to do. Restating
    the models forces each view to be rebuilt from the base canvas as it now is,
    which repairs both a missing view and one still reading a superseded base
    version.

    Returns the primary keys of the scenarios whose view was unhealthy *before*
    the pass, for reporting — the pass itself repairs all of them.
    """
    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import ScenarioType

    modeled = _modeled_scenario_ids()
    scenarios = [
        scenario
        for scenario in Scenario.objects.filter(
            scenario_type=ScenarioType.ALTERNATIVE
        ).select_related("workspace")
        if scenario.pk in modeled
    ]
    _purge_models_for_deleted_scenarios(modeled)
    if not scenarios:
        return []

    unhealthy = [
        scenario.pk for scenario in scenarios if not canvas_view_is_healthy(scenario)
    ]
    selectors = [canvas_model_selector(scenario) for scenario in scenarios]
    logger.info(
        "Reconciling %d scenario canvas view(s); unhealthy before: %s",
        len(scenarios),
        unhealthy,
    )
    run_sqlmesh_plan(
        environment="prod",
        select=selectors,
        restate_models=selectors,
        # Restating hides the project's models from the plan (SQLMesh reads
        # them from state instead), so a scenario whose canvas model was never
        # built would stay unbuilt — the state this pass exists to repair.
        always_include_local_changes=True,
        auto_apply=True,
        no_prompts=True,
    )
    return unhealthy


def drop_scenario_canvas(scenario: Scenario) -> None:
    """Drop *scenario*'s canvas view and its schema, and de-list its model.

    The schema only ever holds that view, so it goes too — leaving it behind
    would keep it visible in the table catalog after the scenario is gone.

    Deleting the scenario removes its canvas model from the blueprint profiles,
    but SQLMesh's stored environments would still list that snapshot — and a
    later plan that promotes such a stale entry points its view at a physical
    object it never creates, failing the whole plan. So the snapshot is removed
    from every environment here, before any plan can trip over it.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"DROP VIEW IF EXISTS {_qi(canvas_view_qualifier(scenario))} CASCADE"
        )
        cursor.execute(f"DROP SCHEMA IF EXISTS {_qi(scenario.target_schema)} CASCADE")
    purge_models_from_environments([canvas_model_fqn(scenario)])
    logger.info("Dropped canvas view %s", canvas_view_qualifier(scenario))


def canvas_model_fqn(scenario: Scenario) -> str:
    """SQLMesh's name for *scenario*'s canvas model."""
    return f'brewgis."scenario_canvas"."canvas_{scenario.pk}"'


def purge_scenario_canvas_tiles(scenario: Scenario) -> None:
    """Purge the tile server's cached tiles for *scenario*'s canvas view.

    Martin scans the database once at startup and caches tiles per source
    without looking at the request, so a paint write stays invisible until its
    source's cache is purged (see
    ``brewgis.workspace.services.tile_server.purge_martin_cache``). tipg serves
    straight from the database and needs nothing.
    """
    if scenario.workspace.tile_server_backend == "martin":
        purge_martin_cache(canvas_view_qualifier(scenario))
