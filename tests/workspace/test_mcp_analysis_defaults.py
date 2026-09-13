# ruff: noqa: ANN201, ANN202, ANN003, PLC0415
"""Tests that the MCP ``run_analysis`` tool defaults ``parcel_table`` to the
scenario's painted-aware canvas view (mirroring AnalysisLaunchForm's default
in views/analysis.py), instead of silently analyzing stale/unpainted data
when a caller doesn't explicitly set it.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

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
class TestRunAnalysisDefaults:
    """Tests for parcel_table/base_canvas_table defaulting in run_analysis."""

    def setup_method(self):
        self.workspace = WorkspaceFactory(base_table="public.base_canvas")
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.run_analysis = _get_run_analysis_tool()

    def test_defaults_parcel_table_to_scenario_canvas_view(self):
        """With no explicit parcel_table, it defaults to the scenario canvas view."""
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
            )

        vars_ = mock_run.call_args.kwargs["vars_"]
        assert (
            vars_["parcel_table"]
            == f"{self.scenario.target_schema}.scenario_{self.scenario.slug}_canvas"
        )
        assert vars_["base_canvas_table"] == "public.base_canvas"

    def test_explicit_parcel_table_overrides_default(self):
        """An explicit parcel_table in params is not clobbered by the default."""
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
                params={"parcel_table": "custom.override_table"},
            )

        vars_ = mock_run.call_args.kwargs["vars_"]
        assert vars_["parcel_table"] == "custom.override_table"

    def test_preflight_checked_against_defaulted_parcel_table(self):
        """The preflight check itself sees the defaulted parcel_table, not empty."""
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
