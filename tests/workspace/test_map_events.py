# ruff: noqa: ANN201, ANN202, ANN002, ANN003
"""Tests for live map events: the websocket consumer, what publishes, and when.

The map page subscribes to its workspace's events over a websocket
(``consumers.MapEventsConsumer``). Server code announces changes with
``services.map_events.notify_map``, on commit, and model signals do so for
layers and background runs. The map re-fetches its layer list from
``map_layers_json``, which must match the list the page was rendered with.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse

from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Basemap
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.routing import websocket_urlpatterns
from brewgis.workspace.services.map_events import _publish
from brewgis.workspace.services.map_events import notify_map
from brewgis.workspace.services.map_events import workspace_group
from brewgis.workspace.services.scenario_canvas import purge_scenario_canvas_tiles
from tests.factories import LayerFactory
from tests.factories import ScenarioFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


def _kinds(map_events: list[tuple[str, dict]]) -> list[str]:
    return [payload["kind"] for _, payload in map_events]


# ─── Consumer ────────────────────────────────────────────────


def _communicator(workspace_pk: int, user) -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns), f"/ws/workspace/{workspace_pk}/map/"
    )
    communicator.scope["user"] = user  # type: ignore[typeddict-unknown-key]
    return communicator


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestMapEventsConsumer:
    async def test_anonymous_connections_are_refused(self):
        workspace = await database_sync_to_async(WorkspaceFactory)()
        communicator = _communicator(workspace.pk, AnonymousUser())

        connected, code = await communicator.connect()

        assert not connected
        assert code == 4403

    async def test_unknown_workspaces_are_refused(self):
        user = await database_sync_to_async(UserFactory)()
        communicator = _communicator(999_999, user)

        connected, _ = await communicator.connect()

        assert not connected

    async def test_forwards_the_workspaces_events_only(self):
        user = await database_sync_to_async(UserFactory)()
        workspace = await database_sync_to_async(WorkspaceFactory)()
        other = await database_sync_to_async(WorkspaceFactory)()
        communicator = _communicator(workspace.pk, user)
        connected, _ = await communicator.connect()
        assert connected

        await sync_to_async(_publish)(
            workspace_group(other.pk), {"kind": "layers.changed"}
        )
        await sync_to_async(_publish)(
            workspace_group(workspace.pk),
            {"kind": "tiles.changed", "layer_keys": ["a"]},
        )

        assert await communicator.receive_json_from() == {
            "kind": "tiles.changed",
            "layer_keys": ["a"],
        }
        assert await communicator.receive_nothing()
        await communicator.disconnect()

    async def test_a_saved_layer_reaches_the_socket(self):
        """End to end: a Layer save commits, its signal publishes, the page hears it."""
        user = await database_sync_to_async(UserFactory)()
        workspace = await database_sync_to_async(WorkspaceFactory)()
        communicator = _communicator(workspace.pk, user)
        await communicator.connect()

        await database_sync_to_async(lambda: LayerFactory(workspace=workspace))()

        assert await communicator.receive_json_from() == {"kind": "layers.changed"}
        await communicator.disconnect()

    async def test_user_events_reach_only_that_user(self):
        alice = await database_sync_to_async(UserFactory)()
        bob = await database_sync_to_async(UserFactory)()
        workspace = await database_sync_to_async(WorkspaceFactory)()
        alices = _communicator(workspace.pk, alice)
        bobs = _communicator(workspace.pk, bob)
        await alices.connect()
        await bobs.connect()

        await database_sync_to_async(notify_map)(
            workspace_id=workspace.pk,
            kind="basemap.changed",
            user_id=alice.pk,
            style="s",
        )

        assert await alices.receive_json_from() == {
            "kind": "basemap.changed",
            "style": "s",
        }
        assert await bobs.receive_nothing()
        await alices.disconnect()
        await bobs.disconnect()


# ─── Publishing ──────────────────────────────────────────────


@pytest.mark.django_db
class TestNotifyMap:
    def test_publishes_only_once_the_transaction_commits(
        self, workspace, map_events, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            notify_map(workspace_id=workspace.pk, kind="tiles.changed", scenario_id=3)
            assert map_events == []

        assert map_events == [
            (f"map.ws.{workspace.pk}", {"kind": "tiles.changed", "scenario_id": 3})
        ]

    def test_a_rolled_back_change_publishes_nothing(
        self, workspace, map_events, django_capture_on_commit_callbacks
    ):
        def change_then_fail() -> None:
            with transaction.atomic():
                notify_map(workspace_id=workspace.pk, kind="layers.changed")
                raise RuntimeError

        with (
            django_capture_on_commit_callbacks(execute=True),
            pytest.raises(RuntimeError),
        ):
            change_then_fail()

        assert map_events == []


@pytest.mark.django_db
class TestSignals:
    def test_layer_create_update_delete_announce_layers_changed(
        self, workspace, map_events, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            layer = LayerFactory(workspace=workspace)
        with django_capture_on_commit_callbacks(execute=True):
            layer.display_order = 5
            layer.save()
        with django_capture_on_commit_callbacks(execute=True):
            layer.delete()

        assert _kinds(map_events) == ["layers.changed"] * 3
        assert {group for group, _ in map_events} == {f"map.ws.{workspace.pk}"}

    def test_groups_and_symbology_announce_layers_changed(
        self, layer, map_events, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            LayerGroup.objects.create(workspace=layer.workspace, name="G")
        with django_capture_on_commit_callbacks(execute=True):
            SymbologyConfigFactory(layer=layer)

        assert _kinds(map_events) == ["layers.changed", "layers.changed"]

    def test_runs_announce_their_status_changes(
        self, workspace, map_events, django_capture_on_commit_callbacks
    ):
        scenario = ScenarioFactory(workspace=workspace)
        with django_capture_on_commit_callbacks(execute=True):
            paint = PaintRun.objects.create(
                workspace=workspace, scenario=scenario, operation="direct", params={}
            )
            paint.status = "failed"
            paint.error_log = "boom"
            paint.save(update_fields=["status", "error_log"])
            # Saves that leave the status alone stay quiet.
            paint.save(update_fields=["error_log"])
            analysis = AnalysisRun.objects.create(
                workspace=workspace, scenario=scenario, modules=["core"]
            )
            analysis.status = "completed"
            analysis.save(update_fields=["status"])
            DataImportRun.objects.create(workspace=workspace, import_type="census")

        payloads = [payload for _, payload in map_events]
        assert payloads == [
            {
                "kind": "paint.run",
                "run_pk": paint.pk,
                "scenario_id": scenario.pk,
                "status": "pending",
                "error": "",
            },
            {
                "kind": "paint.run",
                "run_pk": paint.pk,
                "scenario_id": scenario.pk,
                "status": "failed",
                "error": "boom",
            },
            {
                "kind": "analysis.run",
                "run_pk": analysis.pk,
                "scenario_id": scenario.pk,
                "modules": ["core"],
                "status": "pending",
            },
            {
                "kind": "analysis.run",
                "run_pk": analysis.pk,
                "scenario_id": scenario.pk,
                "modules": ["core"],
                "status": "completed",
            },
            # A completed analysis rewrote the tables behind existing layers.
            {"kind": "tiles.changed"},
            {
                "kind": "import.run",
                "run_pk": DataImportRun.objects.get().pk,
                "import_type": "census",
                "status": "pending",
            },
        ]

    def test_purging_canvas_tiles_announces_the_scenarios_tiles(
        self, workspace, map_events, django_capture_on_commit_callbacks
    ):
        scenario = ScenarioFactory(workspace=workspace)
        with (
            patch("brewgis.workspace.services.scenario_canvas.purge_martin_cache"),
            django_capture_on_commit_callbacks(execute=True),
        ):
            purge_scenario_canvas_tiles(scenario)

        assert map_events == [
            (
                f"map.ws.{workspace.pk}",
                {"kind": "tiles.changed", "scenario_id": scenario.pk},
            )
        ]


@pytest.mark.views
@pytest.mark.django_db
class TestBasemapSelect:
    def test_restyles_only_the_selecting_users_maps(
        self, client, user, workspace, map_events, django_capture_on_commit_callbacks
    ):
        client.force_login(user)
        basemap = Basemap.objects.create(
            name="Dark", basemap_type="vector", style_url="https://style.json"
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                reverse("workspace:basemap_select", args=[workspace.pk]),
                {"basemap_id": basemap.pk},
            )

        assert response.status_code == 200
        assert map_events == [
            (
                f"map.ws.{workspace.pk}.user.{user.pk}",
                {"kind": "basemap.changed", "style": basemap.resolve_style()},
            )
        ]


# ─── Layer list endpoint ─────────────────────────────────────


@pytest.mark.views
@pytest.mark.django_db
class TestMapLayersJson:
    """``map_layers_json`` serves exactly the list the map page embeds."""

    @pytest.fixture
    def setup(self, client, user):
        client.force_login(user)
        workspace = WorkspaceFactory(db_schema="public")
        base = ScenarioFactory(workspace=workspace, scenario_type=ScenarioType.BASE)
        alternative = ScenarioFactory(
            workspace=workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        LayerFactory(workspace=workspace, key="imported", scenario=None)
        LayerFactory(workspace=workspace, key="vmt_alt", scenario=alternative)
        return client, workspace, base, alternative

    @staticmethod
    def _page_layer_data(client, workspace, query: str) -> list[dict]:
        captured: dict = {}

        def fake_render(request, template_name, context=None, *args, **kwargs):
            captured["context"] = context or {}
            return HttpResponse("")

        with patch("brewgis.workspace.views.map.render", side_effect=fake_render):
            client.get(reverse("workspace:workspace_map", args=[workspace.pk]) + query)
        return captured["context"]["layer_data"]

    @pytest.mark.parametrize("which", ["base", "alternative"])
    def test_matches_the_rendered_page(self, setup, which):
        client, workspace, base, alternative = setup
        scenario = base if which == "base" else alternative
        query = f"?scenario={scenario.pk}"
        # Render the page first: it registers the painted-features overlay
        # for an alternative scenario, which both lists then carry.
        expected = self._page_layer_data(client, workspace, query)

        response = client.get(
            reverse("workspace:map_layers_json", args=[workspace.pk]) + query
        )

        assert response.status_code == 200
        assert response.json() == expected
        keys = {layer["id"] for layer in response.json()}
        assert "imported" in keys
        assert ("vmt_alt" in keys) == (which == "alternative")

    def test_requires_login(self, client, workspace):
        response = client.get(reverse("workspace:map_layers_json", args=[workspace.pk]))
        assert response.status_code == 302

    def test_rendering_the_page_twice_announces_nothing(
        self, setup, map_events, django_capture_on_commit_callbacks
    ):
        """Re-stamping the overlay's source on every render must not ping every
        open map, or two tabs on different scenarios would reload each other forever."""
        client, workspace, _base, alternative = setup
        other = ScenarioFactory(
            workspace=workspace, scenario_type=ScenarioType.ALTERNATIVE
        )
        self._page_layer_data(client, workspace, f"?scenario={alternative.pk}")

        with django_capture_on_commit_callbacks(execute=True):
            self._page_layer_data(client, workspace, f"?scenario={other.pk}")
            self._page_layer_data(client, workspace, f"?scenario={alternative.pk}")

        assert "layers.changed" not in _kinds(map_events)
        assert Layer.objects.filter(
            workspace=workspace, key="painted_features"
        ).exists()
