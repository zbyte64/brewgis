# ruff: noqa: ANN201
"""Tests for ``analysis/launch.py:launch_analysis`` — the one way to start an
analysis run, shared by the map view, the full-page form, the MCP tool and the
SACOG demo loader.

The scenario-prerequisite check (parcel source, built-forms export) and the
Celery dispatch are patched; what is under test is how a launch's parameters
are validated and stored on the Scenario the models read them from.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from brewgis.workspace.analysis.launch import AnalysisLaunchError
from brewgis.workspace.analysis.launch import launch_analysis
from brewgis.workspace.services.preflight import PreflightError
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

LAUNCH = "brewgis.workspace.analysis.launch"


@pytest.fixture
def dispatch():
    """The Celery dispatch, with every scenario prerequisite met."""
    with (
        patch(f"{LAUNCH}.scenario_analysis_errors", return_value=[]),
        patch(f"{LAUNCH}.launch_analysis_run") as mock_dispatch,
    ):
        mock_dispatch.return_value = MagicMock(pk=1, status="pending")
        yield mock_dispatch


@pytest.fixture
def scenario(db):
    return ScenarioFactory(workspace=WorkspaceFactory())


@pytest.mark.models
class TestLaunchParameters:
    """How a launch's parameters land on the Scenario the models read them from."""

    def test_params_merge_into_the_stored_ones(self, scenario, dispatch):
        """A module's form carries only its own parameters, so storing them
        must keep every other module's."""
        scenario.analysis_params = {"crop_yield_per_acre": 11.5}
        scenario.save(update_fields=["analysis_params"])

        launch_analysis(
            scenario=scenario,
            modules=["vmt"],
            params={"transport_truck_factor": 0.05},
        )

        scenario.refresh_from_db()
        assert scenario.analysis_params == {
            "crop_yield_per_acre": 11.5,
            "transport_truck_factor": 0.05,
        }
        dispatch.assert_called_once_with(scenario_id=scenario.pk, module_names=["vmt"])

    def test_a_rerun_without_params_keeps_the_stored_ones(self, scenario, dispatch):
        scenario.analysis_params = {"transport_truck_factor": 0.05}
        scenario.save(update_fields=["analysis_params"])

        launch_analysis(scenario=scenario, modules=["vmt"])

        scenario.refresh_from_db()
        assert scenario.analysis_params == {"transport_truck_factor": 0.05}
        dispatch.assert_called_once()

    @pytest.mark.parametrize(
        ("params", "fragment"),
        [
            ({"no_such_parameter": 1}, "Unknown analysis parameter"),
            # The trip-length reference table is region data now, not a parameter.
            (
                {"transport_trip_length_table": "public.zones"},
                "Unknown analysis parameter",
            ),
            ({"transport_truck_factor": "high"}, "must be a float"),
            ({"transport_truck_factor": True}, "must be a float"),
        ],
    )
    def test_invalid_params_are_refused_and_nothing_stored(
        self, scenario, dispatch, params, fragment
    ):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(scenario=scenario, modules=["vmt"], params=params)

        assert fragment in str(excinfo.value)
        dispatch.assert_not_called()
        scenario.refresh_from_db()
        assert scenario.analysis_params == {}

    def test_unknown_module_is_refused(self, scenario, dispatch):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(scenario=scenario, modules=["no_such_module"])

        assert "Unknown modules: no_such_module" in str(excinfo.value)
        dispatch.assert_not_called()

    def test_unmet_prerequisites_refuse_before_params_are_stored(self, scenario):
        """A scenario that cannot be analyzed keeps its parameters untouched."""
        missing = PreflightError("built_form_table", "No built forms exported.")
        with (
            patch(f"{LAUNCH}.scenario_analysis_errors", return_value=[missing]),
            patch(f"{LAUNCH}.launch_analysis_run") as mock_dispatch,
            pytest.raises(AnalysisLaunchError, match="No built forms exported"),
        ):
            launch_analysis(
                scenario=scenario,
                modules=["vmt"],
                params={"transport_truck_factor": 0.05},
            )

        mock_dispatch.assert_not_called()
        scenario.refresh_from_db()
        assert scenario.analysis_params == {}

    @pytest.mark.django_db
    def test_a_workspace_in_no_region_is_refused_as_not_configured(self):
        """A base table outside every region schema has no constraint layers,
        trip-length zones or road network to analyze with, and no region is
        substituted: the launch fails naming the misconfiguration."""
        scenario = ScenarioFactory(
            workspace=WorkspaceFactory(base_table="public.base_canvas")
        )
        with (
            patch(f"{LAUNCH}.ensure_export_exists_isolated"),
            patch(f"{LAUNCH}.check_analysis_prerequisites", return_value=[]),
            patch(f"{LAUNCH}.launch_analysis_run") as mock_dispatch,
            pytest.raises(AnalysisLaunchError, match="not configured for analysis"),
        ):
            launch_analysis(scenario=scenario, modules=["acs_equity"])

        mock_dispatch.assert_not_called()
