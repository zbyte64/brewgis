"""Websocket URL routes (mounted by ``brewgis/config/asgi.py``)."""

from __future__ import annotations

from django.urls import path

from brewgis.workspace.consumers import MapEventsConsumer

websocket_urlpatterns = [
    # Channels' URLRouter takes ASGI apps where django-stubs expects views.
    path(  # type: ignore[call-overload]
        "ws/workspace/<int:workspace_pk>/map/",
        MapEventsConsumer.as_asgi(),  # type: ignore[arg-type]
        name="map_events",
    ),
]
