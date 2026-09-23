# ruff: noqa: ARG002
"""Tests for what an analysis run asks the plan for, and what it accepts back.

An analysis run is only as good as its plan's selection: a module whose model
the plan never materializes leaves the scenario with no results for it, and a
plan that reports success is no evidence to the contrary.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings

from brewgis.workspace.analysis.pipeline import MissingAnalysisResultsError
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.analysis.pipeline import run_modules_sync
from brewgis.workspace.tasks import run_analysis_task
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

PLAN = "brewgis.workspace.analysis.pipeline.run_sqlmesh_plan"
BUILT = "brewgis.workspace.analysis.pipeline.model_fqns_built_in"
PUBLISHED = "brewgis.workspace.analysis.pipeline._list_tables"
REGISTER = "brewgis.workspace.analysis.pipeline.register_result_layer"
SYNC = "brewgis.workspace.analysis.pipeline.run_modules_sync"


class TestPlanSelection:
    """A rerun must still materialize the modules the scenario has never run."""

    def test_plans_new_models_while_restating_built_ones(self, monkeypatch) -> None:
        plans: list[dict[str, Any]] = []
        monkeypatch.setattr(PLAN, lambda **kwargs: plans.append(kwargs))
        monkeypatch.setattr(BUILT, lambda *_a, **_k: ["brewgis.ascn7.core_end_state"])
        monkeypatch.setattr(
            PUBLISHED,
            lambda _schema: [
                "core_end_state",
                "core_increment",
                "trip_generation",
                "vmt",
            ],
        )
        monkeypatch.setattr(REGISTER, lambda **_kwargs: None)

        run_modules_sync(
            modules=["trip_generation", "vmt"], workspace_id=2, scenario_id=7
        )

        (plan,) = plans
        assert plan["restate_models"] == ["brewgis.ascn7.core_end_state"]
        # Restating makes SQLMesh read its models from state, which is how
        # trip_generation/vmt — never built for this scenario — used to be
        # dropped from the plan without a word.
        assert plan["always_include_local_changes"] is True


class TestResultVerification:
    """A requested module with no result view is a failure, not a success."""

    def test_raises_naming_the_module_and_where_it_was_expected(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(PLAN, lambda **_kwargs: None)
        monkeypatch.setattr(BUILT, lambda *_a, **_k: ["brewgis.ascn7.core_end_state"])
        monkeypatch.setattr(
            PUBLISHED, lambda _schema: ["core_end_state", "core_increment"]
        )
        monkeypatch.setattr(REGISTER, lambda **_kwargs: None)

        with pytest.raises(MissingAnalysisResultsError) as excinfo:
            run_modules_sync(modules=["core", "vmt"], workspace_id=2, scenario_id=7)

        assert "vmt -> vmt" in str(excinfo.value)
        assert "analysis__scenario_7" in str(excinfo.value)

    def test_registers_every_view_present_including_earlier_runs_results(
        self, monkeypatch
    ) -> None:
        registered: list[str] = []
        monkeypatch.setattr(PLAN, lambda **_kwargs: None)
        monkeypatch.setattr(BUILT, lambda *_a, **_k: [])
        monkeypatch.setattr(
            PUBLISHED,
            lambda _schema: [
                "core_end_state",
                "core_increment",
                "trip_generation",
                "vmt",
                "water_demand",
            ],
        )
        monkeypatch.setattr(
            REGISTER, lambda **kwargs: registered.append(kwargs["table"])
        )

        result = run_modules_sync(modules=["vmt"], workspace_id=2, scenario_id=7)

        assert registered == [
            "core_end_state",
            "core_increment",
            "trip_generation",
            "vmt",
            "water_demand",
        ]
        assert result["fqtns"] == [
            "analysis__scenario_7.core_end_state",
            "analysis__scenario_7.core_increment",
            "analysis__scenario_7.trip_generation",
            "analysis__scenario_7.vmt",
            "analysis__scenario_7.water_demand",
        ]


@pytest.mark.models
class TestFailedRunReportsCause:
    """The run record has to say why, since the plan says only that it finished."""

    def test_missing_results_fail_the_run_with_the_module_named(
        self, db, monkeypatch
    ) -> None:
        scenario = ScenarioFactory(workspace=WorkspaceFactory())

        def _publish_nothing(**_kwargs: Any) -> Any:
            raise MissingAnalysisResultsError({"vmt": ["vmt"]}, "analysis__scenario_1")

        monkeypatch.setattr(SYNC, _publish_nothing)

        run = run_analysis_pipeline(scenario_id=scenario.pk, module_names=["vmt"])

        assert run.status == "failed"
        assert "vmt -> vmt" in run.failure_cause


class TestTaskTimeLimits:
    """A run must not be governed by the short global Celery limits.

    A run loads the whole project before it plans anything and then
    materializes whatever upstream model the scenario has never built
    (ResNet features, the assessor ArcGIS fetch, NLCD parcel stats), so the
    global 60s soft limit killed run 67 inside ``Context.load()`` and a 300s
    soft limit killed run 69 while its backfill was still building models.
    """

    def test_run_limits_outlive_the_global_ones_and_stay_ordered(self) -> None:
        assert run_analysis_task.soft_time_limit > settings.CELERY_TASK_SOFT_TIME_LIMIT
        assert run_analysis_task.time_limit > settings.CELERY_TASK_TIME_LIMIT

        # A hard limit at or below the soft one SIGKILLs the worker outright,
        # leaving the run stuck at "running" with nothing recorded.
        assert run_analysis_task.soft_time_limit < run_analysis_task.time_limit
