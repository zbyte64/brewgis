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
from django.contrib.gis.geos import Polygon
from django.db import connection

from brewgis.sqlmesh.macros.analysis_blueprints import _drop_inherited_connection
from brewgis.sqlmesh.macros.analysis_blueprints import _parcel_key_type
from brewgis.sqlmesh.macros.analysis_blueprints import analysis_blueprint_profiles
from brewgis.workspace.analysis.module_registry import ANALYSIS_PARAMETERS
from tests.factories import AnalysisRunFactory
from tests.factories import ScenarioFactory
from tests.factories import WorkspaceFactory

# A Fresno-sized bounding box: what makes a workspace have analysis inputs.
_EXTENT = Polygon.from_bbox((-119.95, 36.6, -119.55, 36.92))


class TestParcelKeyType:
    """The parcel-key column type a scenario's models declare.

    It has to come from the scenario's own parcel source: the demo regions key
    parcels on the assessor APN (text) while the legacy base canvas keys them on
    a numeric id, and a model that declares the wrong one fails its first insert
    and cannot join the rest of the scenario's models.
    """

    @pytest.fixture
    def parcel_tables(self, db):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS key_type_probe CASCADE")
            cursor.execute("CREATE SCHEMA key_type_probe")
            cursor.execute(
                "CREATE TABLE key_type_probe.text_keyed (parcel_id varchar(20))"
            )
            cursor.execute(
                "CREATE TABLE key_type_probe.numeric_keyed (parcel_id bigint)"
            )
        yield
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS key_type_probe CASCADE")

    def test_reads_a_text_key(self, parcel_tables):
        assert _parcel_key_type("key_type_probe.text_keyed") == "TEXT"

    def test_reads_a_numeric_key(self, parcel_tables):
        assert _parcel_key_type("key_type_probe.numeric_keyed") == "BIGINT"

    def test_unknown_table_falls_back_to_text(self, db):
        assert _parcel_key_type("no_such_schema.no_such_table") == "TEXT"


class TestScenarioProfiles:
    """Blueprint facts SQLMesh expands one model instance from, per scenario."""

    @pytest.fixture
    def analyzed_scenario(self, db):
        """A scenario analyzed at least once, on a workspace with analysis inputs."""
        workspace = WorkspaceFactory(
            base_table="fresno.base_canvas_reconciled", extent=_EXTENT
        )
        scenario = ScenarioFactory(workspace=workspace)
        AnalysisRunFactory(workspace=workspace, scenario=scenario)
        return scenario

    def test_an_imported_base_is_the_parcel_source_itself(self, db):
        """A base canvas that is not a model is read as the table it is.

        A table carrying the base-canvas columns in any schema is a valid base,
        so the analysis models read it directly — a model FQN would name a table
        no model publishes.
        """
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS blueprint_probe")
            cursor.execute(
                "CREATE TABLE blueprint_probe.base_canvas "
                "(parcel_id bigint PRIMARY KEY, geometry geometry(Polygon, 4326))"
            )
        try:
            workspace = WorkspaceFactory(
                base_table="blueprint_probe.base_canvas", extent=_EXTENT
            )
            scenario = ScenarioFactory(workspace=workspace)
            AnalysisRunFactory(workspace=workspace, scenario=scenario)

            (profile,) = [
                profile
                for profile in analysis_blueprint_profiles("vmt")
                if profile["scenario_pk"] == scenario.pk
            ]
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA IF EXISTS blueprint_probe CASCADE")

        assert profile["parcel_table"] == "blueprint_probe.base_canvas"
        assert profile["base_canvas_table"] == "blueprint_probe.base_canvas"
        # The key type still comes from the source's own column.
        assert profile["parcel_key_type"] == "BIGINT"

    def test_a_model_base_is_named_as_a_model(self, base_canvas_table):
        """The other half of the switch: a base a model publishes keeps its FQN,
        so the analysis depends on the model's snapshot.

        Live-table based, like ``sqlmesh_link_for_table``: a model's view exists
        once a plan has built it, so the table is created here the way a plan
        would leave it (and the test errors rather than replacing a real one).
        """
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS sacog")
            cursor.execute(
                "CREATE TABLE sacog.base_canvas_reconciled "
                "(LIKE public.base_canvas INCLUDING ALL)"
            )
        try:
            workspace = WorkspaceFactory(
                base_table="sacog.base_canvas_reconciled", extent=_EXTENT
            )
            scenario = ScenarioFactory(workspace=workspace)
            AnalysisRunFactory(workspace=workspace, scenario=scenario)

            (profile,) = [
                profile
                for profile in analysis_blueprint_profiles("vmt")
                if profile["scenario_pk"] == scenario.pk
            ]
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS sacog.base_canvas_reconciled")

        assert profile["parcel_table"] == "brewgis.sacog.base_canvas_reconciled"

    def test_inputs_and_crs_are_the_workspaces_own(self, db):
        """Whatever schema its base table is in, a scenario reads its own
        workspace's input models and measures in its workspace's CRS — two
        workspaces over the same base table never share either."""
        state_plane = WorkspaceFactory(
            base_table="fresno.base_canvas_reconciled", extent=_EXTENT, local_srid=2228
        )
        albers = WorkspaceFactory(
            base_table="fresno.base_canvas_reconciled", extent=_EXTENT, local_srid=3310
        )
        scenarios = {}
        for workspace in (state_plane, albers):
            scenario = ScenarioFactory(workspace=workspace)
            AnalysisRunFactory(workspace=workspace, scenario=scenario)
            scenarios[scenario.pk] = workspace

        profiles = {
            profile["scenario_pk"]: profile
            for profile in analysis_blueprint_profiles("env_constraint")
            if profile["scenario_pk"] in scenarios
        }

        assert {
            pk: (profile["workspace_schema"], profile["local_srid"])
            for pk, profile in profiles.items()
        } == {
            pk: (f"wsp{workspace.pk}", workspace.local_srid)
            for pk, workspace in scenarios.items()
        }

    def test_a_workspace_without_an_extent_gets_no_models(self, db):
        """No area is substituted for a base table with no geometry: the scenario
        gets no analysis models (the launch service refuses it as not
        configured), and the other scenarios still load."""
        workspace = WorkspaceFactory(base_table="public.base_canvas", extent=None)
        scenario = ScenarioFactory(workspace=workspace)
        AnalysisRunFactory(workspace=workspace, scenario=scenario)

        assert scenario.pk not in {
            profile["scenario_pk"] for profile in analysis_blueprint_profiles("vmt")
        }

    def test_bakes_the_defaults_and_the_scenarios_overrides(self, analyzed_scenario):
        """Every parameter is baked into the profile — the scenario's own value
        where it has one, the declared default otherwise — so the rendered model
        is self-contained rather than reading a config variable."""
        analyzed_scenario.analysis_params = {"transport_truck_factor": 0.05}
        analyzed_scenario.save(update_fields=["analysis_params"])

        (profile,) = [
            profile
            for profile in analysis_blueprint_profiles("vmt")
            if profile["scenario_pk"] == analyzed_scenario.pk
        ]

        assert {param.name for param in ANALYSIS_PARAMETERS} <= set(profile)
        assert profile["transport_truck_factor"] == 0.05
        assert profile["transport_intrazonal_friction"] == 0.15
        # The scenario type travels as a value: scenario identity metadata every
        # blueprint carries.
        assert profile["scenario_type"] == analyzed_scenario.scenario_type
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
