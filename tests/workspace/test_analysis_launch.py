# ruff: noqa: ANN201, ARG002 -- fixtures injected for their side effects
"""Tests for ``analysis/launch.py:launch_analysis`` — the one way to start an
analysis run, shared by the map view, the full-page form, the MCP tool and the
SACOG demo loader.

Only the scenario-prerequisite check (parcel source, built-forms export) and
the Celery dispatch are patched: the constraint checks run against real tables.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.db import connection

from brewgis.workspace.analysis.launch import AnalysisInputs
from brewgis.workspace.analysis.launch import AnalysisLaunchError
from brewgis.workspace.analysis.launch import launch_analysis
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

LAUNCH = "brewgis.workspace.analysis.launch"


@pytest.fixture
def constraint_tables(db):
    """``launch_test.floodplains`` (geometry column ``geom``) and
    ``launch_test.streams`` (geometry column ``wkb_geometry``)."""
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS launch_test")
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS launch_test.floodplains"
            " (geom geometry(MultiPolygon, 4326))"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS launch_test.streams"
            " (wkb_geometry geometry(MultiLineString, 4326))"
        )


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


def _messages(excinfo: pytest.ExceptionInfo[AnalysisLaunchError]) -> list[str]:
    return [error.message for error in excinfo.value.errors]


@pytest.mark.models
class TestConstraintTables:
    """A constraint the model would fail on is refused before a run exists."""

    def test_stored_bare_constraint_with_no_public_table_is_refused(
        self, scenario, dispatch
    ):
        """The configuration behind AnalysisRun #135: a bare ``floodplains``
        resolves in ``public``, where no such table exists. A rerun (no inputs)
        must be refused instead of failing with UndefinedTable mid-plan."""
        scenario.constraints = [
            {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"}
        ]
        scenario.save(update_fields=["constraints"])

        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(scenario=scenario, modules=["vmt"])

        assert _messages(excinfo) == [
            "Constraint table public.floodplains does not exist."
        ]
        dispatch.assert_not_called()

    def test_missing_geometry_column_is_refused_and_nothing_stored(
        self, scenario, constraint_tables, dispatch
    ):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(
                scenario=scenario,
                modules=["env_constraint"],
                inputs=AnalysisInputs(
                    constraints=[{"table": "launch_test.streams"}],
                    column_mapping={"pop": "population"},
                ),
            )

        assert _messages(excinfo) == [
            "Constraint table launch_test.streams has no geometry column 'geom'."
        ]
        dispatch.assert_not_called()
        scenario.refresh_from_db()
        assert scenario.constraints == []
        assert scenario.column_mapping == {}

    def test_existing_tables_are_accepted_and_stored_complete(
        self, scenario, constraint_tables, dispatch
    ):
        """A schema-qualified (or catalog-qualified) table that exists is
        stored as a complete entry, with the defaults the model would apply."""
        launch_analysis(
            scenario=scenario,
            modules=["env_constraint"],
            inputs=AnalysisInputs(
                constraints=[
                    {"table": "launch_test.floodplains"},
                    {
                        "table": "brewgis.launch_test.streams",
                        "geom_col": "wkb_geometry",
                        "discount_pct": 40,
                    },
                ]
            ),
        )

        scenario.refresh_from_db()
        assert scenario.constraints == [
            {
                "table": "launch_test.floodplains",
                "discount_pct": 100,
                "geom_col": "geom",
            },
            {
                "table": "brewgis.launch_test.streams",
                "discount_pct": 40,
                "geom_col": "wkb_geometry",
            },
        ]
        dispatch.assert_called_once_with(
            scenario_id=scenario.pk, module_names=["env_constraint"]
        )

    def test_constraints_are_not_checked_when_the_chain_never_reads_them(
        self, scenario, dispatch
    ):
        """``acs_equity`` does not resolve through env_constraint, so a stale
        constraint does not block it."""
        scenario.constraints = [
            {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"}
        ]
        scenario.save(update_fields=["constraints"])

        launch_analysis(scenario=scenario, modules=["acs_equity"])

        dispatch.assert_called_once()

    @pytest.mark.parametrize(
        ("entry", "fragment"),
        [
            ({"discount_pct": 50}, "names no table"),
            (
                {"table": "launch_test.floodplains", "discount_pct": 150},
                "from 0 to 100",
            ),
            (
                {"table": "launch_test.floodplains", "discount_pct": True},
                "from 0 to 100",
            ),
            (
                {"table": "launch_test.floodplains", "buffer": 10},
                "unknown keys: buffer",
            ),
            ("launch_test.floodplains", "is not an object"),
        ],
    )
    def test_malformed_entries_are_refused(
        self, scenario, constraint_tables, dispatch, entry, fragment
    ):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(
                scenario=scenario,
                modules=["env_constraint"],
                inputs=AnalysisInputs(constraints=[entry]),
            )

        assert fragment in str(excinfo.value)
        dispatch.assert_not_called()


@pytest.mark.models
class TestStoredInputs:
    """How a launch's inputs land on the Scenario the models read them from."""

    def test_omitted_inputs_keep_the_stored_ones_and_params_merge(
        self, scenario, constraint_tables, dispatch
    ):
        stored_constraints = [
            {
                "table": "launch_test.floodplains",
                "discount_pct": 100,
                "geom_col": "geom",
            }
        ]
        scenario.constraints = stored_constraints
        scenario.column_mapping = {"pop": "population"}
        scenario.analysis_params = {"crop_yield_per_acre": 11.5}
        scenario.save(
            update_fields=["constraints", "column_mapping", "analysis_params"]
        )

        launch_analysis(
            scenario=scenario,
            modules=["vmt"],
            inputs=AnalysisInputs(params={"transport_truck_factor": 0.05}),
        )

        scenario.refresh_from_db()
        assert scenario.constraints == stored_constraints
        assert scenario.column_mapping == {"pop": "population"}
        assert scenario.analysis_params == {
            "crop_yield_per_acre": 11.5,
            "transport_truck_factor": 0.05,
        }

    def test_given_inputs_replace_the_stored_ones(
        self, scenario, constraint_tables, dispatch
    ):
        scenario.constraints = [
            {
                "table": "launch_test.floodplains",
                "discount_pct": 100,
                "geom_col": "geom",
            }
        ]
        scenario.column_mapping = {"pop": "population", "hh": "households"}
        scenario.save(update_fields=["constraints", "column_mapping"])

        launch_analysis(
            scenario=scenario,
            modules=["vmt"],
            inputs=AnalysisInputs(constraints=[], column_mapping={"du": "units"}),
        )

        scenario.refresh_from_db()
        assert scenario.constraints == []
        assert scenario.column_mapping == {"du": "units"}

    @pytest.mark.parametrize(
        ("inputs", "fragment"),
        [
            (
                AnalysisInputs(params={"no_such_parameter": 1}),
                "Unknown analysis parameter",
            ),
            (
                AnalysisInputs(params={"transport_truck_factor": "high"}),
                "must be a float",
            ),
            (
                AnalysisInputs(params={"transport_truck_factor": True}),
                "must be a float",
            ),
            (
                AnalysisInputs(column_mapping={"population": "pop"}),
                "Unknown canonical column",
            ),
            (AnalysisInputs(column_mapping={"pop": ""}), "must name a column"),
        ],
    )
    def test_invalid_inputs_are_refused_and_nothing_stored(
        self, scenario, dispatch, inputs, fragment
    ):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(scenario=scenario, modules=["vmt"], inputs=inputs)

        assert fragment in str(excinfo.value)
        dispatch.assert_not_called()
        scenario.refresh_from_db()
        assert scenario.analysis_params == {}
        assert scenario.column_mapping == {}

    def test_unknown_module_is_refused(self, scenario, dispatch):
        with pytest.raises(AnalysisLaunchError) as excinfo:
            launch_analysis(scenario=scenario, modules=["no_such_module"])

        assert "Unknown modules: no_such_module" in str(excinfo.value)
        dispatch.assert_not_called()
