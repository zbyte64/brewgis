"""Adopting a workspace's base layer — the one path every base-table change takes.

A workspace's base layer is its ``base_table`` (or the built-form fill over it,
``Workspace.effective_base_table``). Changing it — the base-canvas picker, a
workspace package import or re-attach (``services.workspace_package``) — has to
do the same four things, so they live here once:

1. persist ``base_table``/``fill_built_form`` (and the extent, when the caller
   knows it) *before* the plan, because the blueprint macros read those rows
   while SQLMesh loads the project;
2. plan the models over the new base in **one** plan — the base model itself
   when it is one the plan must build (a packaged base canvas), the fill, and
   every ALTERNATIVE scenario's canvas. Any plan promotes the whole
   environment's virtual layer, so a canvas selected but not built would be
   promoted over a physical object nothing created, failing the promotion;
3. set the extent from the base layer when the caller did not supply one;
4. register the base-canvas layer and purge Martin's cached tiles for every
   view whose rows the plan rewrote.
"""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
from typing import TYPE_CHECKING
from typing import Any

from brewgis.sqlmesh.macros.built_form_fill_blueprints import (
    MODEL_SCHEMA as FILL_SCHEMA,
)
from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.scenario_canvas import canvas_model_selector
from brewgis.workspace.services.scenario_canvas import modeled_scenarios
from brewgis.workspace.services.scenario_canvas import purge_scenario_canvas_tiles
from brewgis.workspace.services.tile_server import ensure_martin_source
from brewgis.workspace.services.workspace_extent import base_table_extent

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.contrib.gis.geos import Polygon

    from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)


def plan_fresh(**plan_kwargs: Any) -> None:
    """Run a prod plan that renders the project in a private, empty cache directory.

    The models over a workspace's base layer and inputs are blueprinted from
    ``Workspace`` rows, and SQLMesh caches rendered model definitions on disk
    keyed by model-file mtimes, never by those rows — so a plan through the
    shared cache can render a workspace's blueprints as they were before the
    row changed (two sources of one input model at once, say). The analysis
    pipeline renders every run in its own directory for the same reason
    (``analysis.pipeline.run_modules_sync``).
    """
    with tempfile.TemporaryDirectory(prefix="brewgis-sqlmesh-cache-") as cache_dir:
        run_sqlmesh_plan(environment="prod", cache_dir=cache_dir, **plan_kwargs)


def fill_model_fqn(workspace_pk: int) -> str:
    """SQLMesh's name for *workspace_pk*'s built-form fill model.

    Mirrors ``services.scenario_canvas.canvas_model_fqn``: the identifier parts
    are double-quoted so the FQN survives selector parsing.
    """
    return f'brewgis."{FILL_SCHEMA}"."fill_{workspace_pk}"'


def adopt_base_table(
    workspace: Workspace,
    *,
    base_table: str,
    fill_built_form: bool,
    extent: Polygon | None = None,
    base_selectors: Sequence[str] = (),
) -> list[str]:
    """Make *base_table* the workspace's base layer and rebuild what reads it.

    *base_selectors* are models the plan must build for the base itself to exist
    (a packaged base canvas and its bridge); the fill and the scenario canvases
    follow in the same plan. *extent* is the workspace extent when the caller
    knows it (a package manifest); otherwise it is taken from the base layer
    once the plan has built it. Returns the plan's selectors.
    """
    workspace.base_table = base_table
    workspace.fill_built_form = fill_built_form
    update_fields = ["base_table", "fill_built_form"]
    if extent is not None:
        workspace.extent = extent
        update_fields.append("extent")
    # Persisted before the plan: the blueprint macros read these columns while
    # loading the project, so the models over the new base only exist in the
    # plan that is about to run once the row is on disk.
    workspace.save(update_fields=update_fields)

    canvas_scenarios = modeled_scenarios(
        workspace.scenarios.filter(scenario_type=ScenarioType.ALTERNATIVE)
    )
    selectors = [*base_selectors]
    if fill_built_form:
        selectors.append(fill_model_fqn(workspace.pk))
    else:
        # Flipping the flag off de-lists this workspace's fill model from the
        # blueprint; drop the now-orphaned snapshot so a later plan never
        # promotes a model the project no longer defines.
        purge_models_from_environments([fill_model_fqn(workspace.pk)])
    selectors += [canvas_model_selector(scenario) for scenario in canvas_scenarios]
    if selectors:
        plan_fresh(
            select=selectors,
            # A Python model's SQLMesh fingerprint covers its *definition*, not
            # the SQL its ``execute`` returns — so a change to the fill rule (or
            # to the library it matches against) leaves the snapshot looking
            # unchanged, and the workspace would keep reading a table built by
            # the previous rule. Adopting a base is a request to rebuild, so the
            # fill model is always recomputed; the canvases over it follow their
            # parent's data change into the same plan.
            restate_models=[fill_model_fqn(workspace.pk)] if fill_built_form else False,
            # A restating plan otherwise reads every model's definition from
            # SQLMesh's state rather than from the project, so the fill rule
            # that would run is the one in state the last time this environment
            # was planned. The analysis repair pass asks for the same thing for
            # the same reason (``services.scenario_analysis``).
            always_include_local_changes=True,
            auto_apply=True,
            no_prompts=True,
        )

    if extent is None:
        workspace.extent = base_table_extent(workspace.base_table)
        workspace.save(update_fields=["extent"])

    schema, table = workspace.effective_base_table().split(".", 1)
    register_result_layer(
        workspace.pk,
        schema,
        table,
        key=BASE_CANVAS_LAYER_KEY,
        name="Base Canvas",
        description=f"Workspace base canvas ({workspace.effective_base_table()})",
    )

    # The plan rewrote the rows behind this workspace's base layer and promoted
    # every canvas view over it. Martin caches rendered tile bytes per source
    # without ever looking at the request, and discovers tables only at its own
    # startup, so without this the map keeps drawing whatever it rendered
    # before the plan.
    if workspace.tile_server_backend == "martin":
        for scenario in canvas_scenarios:
            purge_scenario_canvas_tiles(scenario)
        ensure_martin_source(workspace.effective_base_table())

    logger.info(
        "Workspace %s base_table=%s fill_built_form=%s (planned %s)",
        workspace.pk,
        workspace.base_table,
        workspace.fill_built_form,
        selectors,
    )
    return selectors


def create_base_scenario(workspace: Workspace) -> Scenario:
    """Give a new workspace the base scenario it paints against.

    BASE scenarios have no canvas view — they resolve straight to
    ``workspace.base_table`` via ``Scenario.base_layer_source()``.
    """
    today = dt.date.today()  # noqa: DTZ011
    return Scenario.objects.create(
        workspace=workspace,
        name="Base Scenario",
        scenario_type=ScenarioType.BASE,
        base_year=today.year,
        horizon_year=today.year + 20,
    )
