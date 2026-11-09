"""Contract: an analysis run plans every model its modules read.

A model is only planned when a selector names it, so a run whose selection
(``pipeline.plan_selection``) misses a dependency reads a relation nothing ever
built. A server that has run the region construction pipelines has the shared
models from those plans and never notices; a fresh install that only imports
workspace packages has none of them, and the first analysis died in
``core_end_state`` with ``schema "california" does not exist`` — the CEC/CIMIS
zone models every scenario reads.

The one dependency a run is allowed not to plan is the workspace's base layer —
its base table, the built-form fill over it and the scenario canvases, built
when the base is adopted (``services.workspace_base.adopt_base_table``). Tables
that are not SQLMesh models at all (the built-forms table the launch service
exports before every run) are outside SQLMesh's plan either way.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from brewgis.workspace.analysis.module_registry import MODULE_SQLMESH_SELECTORS
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import plan_selection
from brewgis.workspace.analysis.sqlmesh_runner import get_context
from brewgis.workspace.models import Scenario
from brewgis.workspace.services.scenario_canvas import canvas_model_fqn
from brewgis.workspace.services.workspace_base import fill_model_fqn

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    # transaction=True so the parity fixture's committed blueprint rows are
    # visible to SQLMesh's forked model-loading workers.
    pytest.mark.django_db(transaction=True),
]


def test_every_module_plans_every_model_it_reads(parity_scenario: str) -> None:
    scenario = Scenario.objects.select_related("workspace").get(
        pk=int(parity_scenario.removeprefix("ascn"))
    )
    workspace = scenario.workspace
    cache_dir = tempfile.mkdtemp(prefix="brewgis-plan-selection-")
    context = get_context(cache_dir=cache_dir)
    try:
        dag = context.dag

        def models(selector: str) -> set[str]:
            """The model FQNs *selector* plans (``+`` adds everything upstream)."""
            model = context.get_model(selector.removeprefix("+"))
            assert model is not None, f"selector {selector!r} names no model"
            if selector.startswith("+"):
                return {model.fqn, *dag.upstream(model.fqn)}
            return {model.fqn}

        base_layer: set[str] = set()
        for name in (
            workspace.base_table,
            fill_model_fqn(workspace.pk),
            *(canvas_model_fqn(s) for s in workspace.scenarios.all()),
        ):
            model = context.get_model(name)
            if model is not None:
                base_layer |= {model.fqn, *dag.upstream(model.fqn)}

        unplanned: dict[str, list[str]] = {}
        for module in MODULE_SQLMESH_SELECTORS:
            selects, inputs = plan_selection(
                resolve_module_order([module]),
                scenario_id=scenario.pk,
                workspace_schema=workspace.input_schema,
            )
            planned = set().union(*(models(s) for s in selects + inputs))
            read = set().union(
                *(set(dag.upstream(f)) for s in selects for f in models(s))
            )
            missing = sorted(
                fqn
                for fqn in read - planned - base_layer
                # Not a SQLMesh model (a table Django writes): no plan builds it.
                if context.get_model(fqn) is not None
                and not context.get_model(fqn).kind.is_external
            )
            if missing:
                unplanned[module] = missing
    finally:
        for adapter in (context.engine_adapters or {}).values():
            adapter.close()
        context.close()
        shutil.rmtree(cache_dir, ignore_errors=True)

    assert not unplanned, (
        "a run of these modules reads models its plan never selects, so on a"
        " server that has not built them by some other plan the run fails on a"
        f" missing relation: {unplanned}"
    )
