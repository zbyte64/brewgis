# ruff: noqa: ANN201, ANN202, ANN003, PLC0415
"""Tests that the MCP ``run_analysis`` tool analyzes the scenario's own parcel
source and stores its parameters on the scenario through the same launch
service as the map view's forms (``brewgis/workspace/analysis/launch.py``).

The analysis models derive their inputs from the scenario (its painted-aware
canvas view for an ALTERNATIVE scenario, the workspace's base canvas otherwise)
and read their parameters off the Scenario row (see
``sqlmesh/macros/analysis_blueprints.py``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.models import ScenarioType
from brewgis.workspace.services.preflight import PreflightError
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

LAUNCH = "brewgis.workspace.analysis.launch"


def _get_run_analysis_tool():
    """Register the analysis MCP tools and return the ``run_analysis`` function."""
    from brewgis.workspace.mcp.tools.analysis import register_tools

    captured: dict[str, Any] = {}

    def capture_tool(**_kw):
        def decorator(f):
            captured[f.__name__] = f
            return f

        return decorator

    mock_server = MagicMock()
    mock_server.tool = capture_tool
    register_tools(mock_server)
    return captured["run_analysis"]


@pytest.mark.django_db
class TestRunAnalysisScenarioInputs:
    """Tests for how ``run_analysis`` resolves and records a scenario's inputs."""

    def setup_method(self):
        self.workspace = WorkspaceFactory(base_table="fresno.base_canvas_reconciled")
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.run_analysis = _get_run_analysis_tool()

    def test_preflight_checked_against_the_scenarios_own_parcel_source(self):
        """An ALTERNATIVE scenario is checked against its canvas view — the
        base canvas plus any painted edits — not the raw workspace table."""
        with (
            patch(f"{LAUNCH}.ensure_export_exists_isolated"),
            patch(
                f"{LAUNCH}.check_analysis_prerequisites", return_value=[]
            ) as mock_preflight,
            patch(f"{LAUNCH}.launch_analysis_run"),
        ):
            self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
            )

        assert mock_preflight.call_args.kwargs["parcel_table"] == (
            f"{self.scenario.target_schema}.scenario_{self.scenario.slug}_canvas"
        )
        assert mock_preflight.call_args.kwargs["base_canvas_table"] == (
            "fresno.base_canvas_reconciled"
        )

    def test_params_are_stored_on_the_scenario(self):
        """``params`` are analysis parameters, merged into the scenario's stored
        values, so the models loaded for this run (and any later rerun) use them."""
        with (
            patch(f"{LAUNCH}.scenario_analysis_errors", return_value=[]),
            patch(f"{LAUNCH}.launch_analysis_run") as mock_run,
        ):
            mock_run.return_value = MagicMock(pk=1, status="pending")
            self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
                modules=["vmt"],
                params={"transport_truck_factor": 0.05},
            )

        self.scenario.refresh_from_db()
        assert self.scenario.analysis_params == {"transport_truck_factor": 0.05}
        assert mock_run.call_args.kwargs["scenario_id"] == self.scenario.pk

    def test_failed_preflight_does_not_store_or_launch(self):
        """A prerequisite failure stops the run before touching the scenario."""
        with (
            patch(
                f"{LAUNCH}.scenario_analysis_errors",
                return_value=[PreflightError(field="parcel_table", message="nope")],
            ),
            patch(f"{LAUNCH}.launch_analysis_run") as mock_run,
        ):
            result = self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
                params={"transport_truck_factor": 0.05},
            )

        assert result["status"] == "FAILURE"
        assert "nope" in result["message"]
        mock_run.assert_not_called()
        self.scenario.refresh_from_db()
        assert self.scenario.analysis_params == {}

    def test_table_overrides_are_refused(self):
        """Constraint tables are region data built by SQLMesh: the old
        ``constraints`` input is an unknown parameter, not silently ignored."""
        with patch(f"{LAUNCH}.launch_analysis_run") as mock_run:
            result = self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
                params={"constraints": [{"table": "fresno.floodplains"}]},
            )

        assert result["status"] == "FAILURE"
        assert "constraints" in result["message"]
        mock_run.assert_not_called()
