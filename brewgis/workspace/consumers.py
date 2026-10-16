"""Websocket consumers — the map page's live event stream.

``MapEventsConsumer`` subscribes a map page to its workspace's events (see
``services/map_events.py``). The stream only goes from server to client, so
messages from the client are ignored.
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from brewgis.workspace.models import Workspace
from brewgis.workspace.services.map_events import user_group
from brewgis.workspace.services.map_events import workspace_group

# Close code for a refused subscription (4000-4999 is application-defined).
FORBIDDEN = 4403


class MapEventsConsumer(JsonWebsocketConsumer):
    """Forward a workspace's map events to one map page."""

    groups_joined: list[str]

    def connect(self) -> None:
        self.groups_joined = []
        user = self.scope.get("user")
        # URLRouter always sets url_route; the scope TypedDict marks it optional.
        workspace_pk = self.scope["url_route"]["kwargs"]["workspace_pk"]  # type: ignore[typeddict-item]
        if (
            user is None
            or not user.is_authenticated
            or not Workspace.objects.filter(pk=workspace_pk).exists()
        ):
            self.close(code=FORBIDDEN)
            return
        self.groups_joined = [
            workspace_group(workspace_pk),
            user_group(workspace_pk, user.pk),
        ]
        for group in self.groups_joined:
            async_to_sync(self.channel_layer.group_add)(group, self.channel_name)
        self.accept()

    def disconnect(self, code: int) -> None:  # noqa: ARG002
        for group in self.groups_joined:
            async_to_sync(self.channel_layer.group_discard)(group, self.channel_name)

    def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Ignore client messages: the stream only goes from server to client."""

    def map_event(self, event: dict[str, Any]) -> None:
        self.send_json(event["payload"])
