# ruff: noqa: ANN201, ANN202, ANN003, PLC0415
"""Tests that the MCP ``run_analysis`` tool analyzes the scenario's own parcel
source and persists per-run parameters on the scenario.

The analysis models derive their inputs from the scenario (its painted-aware
canvas view for an ALTERNATIVE scenario, the workspace's base canvas otherwise)
and read constraints/column mapping off the Scenario row, so this tool validates
those derived inputs and stores the parameters rather than passing plan
variables (see ``sqlmesh/macros/analysis_blueprints.py``).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.models import ScenarioType
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory


def _get_run_analysis_tool():
    """Register the analysis MCP tools and return the ``run_analysis`` function."""
    from brewgis.workspace.mcp.tools.analysis import register_tools

    captured: dict[str, object] = {}

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
        self.workspace = WorkspaceFactory(base_table="public.base_canvas")
        self.scenario = ScenarioFactory(
            workspace=self.workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self.run_analysis = _get_run_analysis_tool()

    def test_preflight_checked_against_the_scenarios_own_parcel_source(self):
        """An ALTERNATIVE scenario is checked against its canvas view — the
        base canvas plus any painted edits — not the raw workspace table."""
        with (
            patch(
                "brewgis.workspace.mcp.tools.analysis.check_analysis_prerequisites",
                return_value=[],
            ) as mock_preflight,
            patch("brewgis.workspace.mcp.tools.analysis.run_analysis_pipeline"),
        ):
            self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
            )

        assert mock_preflight.call_args.kwargs["parcel_table"] == (
            f"{self.scenario.target_schema}.scenario_{self.scenario.slug}_canvas"
        )
        assert mock_preflight.call_args.kwargs["base_canvas_table"] == (
            "public.base_canvas"
        )

    def test_parameters_are_persisted_on_the_scenario(self):
        """``params`` become the scenario's stored parameters, so the models
        loaded for this run (and any later rerun) use them."""
        constraints = [{"table": "floodplains", "discount_pct": 50, "geom_col": "geom"}]
        with (
            patch(
                "brewgis.workspace.mcp.tools.analysis.check_analysis_prerequisites",
                return_value=[],
            ),
            patch(
                "brewgis.workspace.mcp.tools.analysis.run_analysis_pipeline"
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(pk=1, status="pending")
            self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
                modules=["core"],
                params={
                    "constraints": constraints,
                    "column_mapping": {"pop": "population"},
                },
            )

        self.scenario.refresh_from_db()
        assert self.scenario.constraints == constraints
        assert self.scenario.column_mapping == {"pop": "population"}
        assert mock_run.call_args.kwargs["scenario_id"] == self.scenario.pk

    def test_failed_preflight_does_not_persist_or_launch(self):
        """A prerequisite failure stops the run before touching the scenario."""
        from brewgis.workspace.services.preflight import PreflightError

        with (
            patch(
                "brewgis.workspace.mcp.tools.analysis.check_analysis_prerequisites",
                return_value=[PreflightError(field="parcel_table", message="nope")],
            ),
            patch(
                "brewgis.workspace.mcp.tools.analysis.run_analysis_pipeline"
            ) as mock_run,
        ):
            result = self.run_analysis(
                workspace_slug=str(self.workspace.pk),
                scenario_slug=str(self.scenario.pk),
                params={"constraints": [{"table": "x", "discount_pct": 1}]},
            )

        assert result["status"] == "FAILURE"
        mock_run.assert_not_called()
        self.scenario.refresh_from_db()
        assert self.scenario.constraints == []
