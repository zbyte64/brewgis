# ruff: noqa: ANN201, ARG002
"""Tests for the analysis blueprint profiles.

These are the per-scenario facts SQLMesh expands one instance of every
``models/analysis/**`` model from (see ``macros/analysis_blueprints.py``), so
what a profile carries is what the model is rendered with — including the
scenario's own analysis parameters, which were config variables before they
were baked here.
"""

from __future__ import annotations

import multiprocessing

import pytest
from django.db import connection

from brewgis.sqlmesh.macros.analysis_blueprints import _drop_inherited_connection
from brewgis.sqlmesh.macros.analysis_blueprints import analysis_blueprint_profiles
from brewgis.workspace.analysis.module_registry import ANALYSIS_PARAMETERS
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory


class TestScenarioProfiles:
    """Blueprint facts SQLMesh expands one model instance from, per scenario."""

    @pytest.fixture
    def analyzed_scenario(self, db):
        """A scenario analyzed at least once, on a SQLMesh-managed base table."""
        workspace = WorkspaceFactory(base_table="fresno.base_canvas_reconciled")
        scenario = ScenarioFactory(workspace=workspace)
        AnalysisRunFactory(workspace=workspace, scenario=scenario)
        return scenario

    def test_bakes_the_defaults_and_the_scenarios_overrides(self, analyzed_scenario):
        """Every parameter is baked into the profile — the scenario's own value
        where it has one, the declared default otherwise — so the rendered model
        is self-contained rather than reading a config variable."""
        analyzed_scenario.analysis_params = {"transport_avg_trip_length_mi": 9.87}
        analyzed_scenario.save(update_fields=["analysis_params"])

        (profile,) = [
            profile
            for profile in analysis_blueprint_profiles("vmt")
            if profile["scenario_pk"] == analyzed_scenario.pk
        ]

        assert {param.name for param in ANALYSIS_PARAMETERS} <= set(profile)
        assert profile["transport_avg_trip_length_mi"] == 9.87
        assert profile["transport_circuity_factor"] == 1.2
        assert profile["model_table"] == "vmt"


class TestForkedWorkerConnections:
    """SQLMesh loads models in forked workers, and the profiles are read there."""

    def test_a_childs_teardown_leaves_the_parents_connection_usable(self, db):
        """The child takes its own connection without terminating the one its
        parent is still using. Closing the inherited connection instead sends a
        Terminate over the socket both processes share, and the parent — which
        goes on loading models, planning and writing result rows — then fails
        with "server closed the connection unexpectedly".
        """

        def query(value: int) -> int:
            with connection.cursor() as cursor:
                cursor.execute("SELECT %s", [value])
                return cursor.fetchone()[0]

        assert query(1) == 1

        def child() -> None:
            _drop_inherited_connection()
            assert query(42) == 42

        process = multiprocessing.get_context("fork").Process(target=child)
        process.start()
        process.join()

        assert process.exitcode == 0
        assert query(7) == 7
