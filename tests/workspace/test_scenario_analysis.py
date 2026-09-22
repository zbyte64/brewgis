# ruff: noqa: ANN201, ARG002
"""Tests for the scenario analysis lifecycle — result schema drop and reconciliation.

Requires a PostgreSQL+PostGIS database.
"""

from __future__ import annotations

import pytest
from django.db import connection

from brewgis.workspace.analysis import module_registry
from brewgis.workspace.services.canvas_view_manager import _qi
from brewgis.workspace.services.scenario_analysis import drop_scenario_analysis
from brewgis.workspace.services.scenario_analysis import reconcile_scenario_analyses
from brewgis.workspace.services.scenario_analysis import scenario_analysis_fqns
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

PLAN = "brewgis.workspace.services.scenario_analysis.run_sqlmesh_plan"
BUILT = "brewgis.workspace.services.scenario_analysis.model_fqns_built_in"


class TestScenarioAnalysisFqns:
    """``scenario_analysis_fqns`` names the scenario's own model instances."""

    def test_names_every_model_the_scenario_owns(self):
        fqns = scenario_analysis_fqns(7)
        assert len(fqns) == len(
            {
                model
                for models in module_registry.MODULE_SQLMESH_SELECTORS.values()
                for model in models
            }
        )
        assert all(fqn.startswith("brewgis.ascn7.") for fqn in fqns)
        assert "brewgis.ascn7.core_end_state" in fqns


@pytest.mark.integration
class TestDropScenarioAnalysis:
    """Dropping a scenario's analysis takes its result schema with it."""

    def test_removes_the_result_schema_and_everything_in_it(self, db):
        schema = module_registry.result_schema_name(42)
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_qi(schema)}")
            cursor.execute(
                f"CREATE VIEW {_qi(schema)}.core_end_state AS SELECT 1 AS pop"
            )

        drop_scenario_analysis(42)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.schemata "
                "WHERE schema_name = %s",
                [schema],
            )
            assert cursor.fetchone()[0] == 0

    def test_is_a_no_op_when_the_scenario_has_no_results(self, db):
        """A scenario that was never analyzed has no schema to drop."""
        drop_scenario_analysis(4242)  # must not raise


@pytest.mark.integration
class TestReconcileScenarioAnalyses:
    """Reconciliation restates every *built* model, and only those."""

    def test_restates_the_models_a_plan_can_restate(self, db, monkeypatch):
        scenario = ScenarioFactory(
            workspace=WorkspaceFactory(base_table="fresno.base_canvas_reconciled")
        )
        AnalysisRunFactory(workspace=scenario.workspace, scenario=scenario)
        built = [f"brewgis.ascn{scenario.pk}.core_end_state"]
        plans: list[dict] = []
        monkeypatch.setattr(BUILT, lambda *_args, **_kwargs: built)
        monkeypatch.setattr(PLAN, lambda **kwargs: plans.append(kwargs))

        reconcile_scenario_analyses()

        assert len(plans) == 1
        plan = plans[0]
        assert plan["environment"] == "prod"
        # Everything the scenario owns is selected, but only the models that
        # have been built are restated — SQLMesh refuses to restate a model it
        # has never built.
        assert plan["select"] == scenario_analysis_fqns(scenario.pk)
        assert plan["restate_models"] == built

    def test_plans_nothing_when_no_model_has_been_built(self, db, monkeypatch):
        scenario = ScenarioFactory(
            workspace=WorkspaceFactory(base_table="fresno.base_canvas_reconciled")
        )
        AnalysisRunFactory(workspace=scenario.workspace, scenario=scenario)
        plans: list[dict] = []
        monkeypatch.setattr(BUILT, lambda *_args, **_kwargs: [])
        monkeypatch.setattr(PLAN, lambda **kwargs: plans.append(kwargs))

        reconcile_scenario_analyses()

        assert plans == []

    def test_plans_nothing_when_there_are_no_analyzed_scenarios(self, db, monkeypatch):
        plans: list[dict] = []
        monkeypatch.setattr(BUILT, lambda *_args, **_kwargs: ["brewgis.ascn1.x"])
        monkeypatch.setattr(PLAN, lambda **kwargs: plans.append(kwargs))

        reconcile_scenario_analyses()

        assert plans == []
