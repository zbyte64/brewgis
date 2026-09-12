# ruff: noqa: ANN201
"""Regression tests for scenario report generation (brewgis/workspace/tasks.py).

_build_report_scenario_metrics previously referenced a non-existent
`scenario.canvas_view_name` attribute and queried made-up column names,
so generating a Scenario Comparison report always raised/failed. These
tests pin the fixed behavior against a scenario with no canvas view yet
(the common case for a freshly created scenario).
"""

from __future__ import annotations

from django.test import TestCase

from brewgis.workspace.tasks import _build_report_scenario_metrics
from tests.factories import ScenarioFactory


class TestBuildReportScenarioMetrics(TestCase):
    def test_missing_canvas_view_returns_none_metrics_without_raising(self):
        scenario = ScenarioFactory()

        metrics = _build_report_scenario_metrics(scenario)

        assert metrics == {
            "total_population": None,
            "total_households": None,
            "total_du": None,
            "total_employment": None,
            "total_vmt": None,
            "total_water": None,
            "total_energy": None,
            "total_land_consumed_acres": None,
        }
