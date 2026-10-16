"""Map events — tell every open map page what changed, over its websocket.

The map page holds one websocket (``consumers.MapEventsConsumer``) per
workspace. Server code that changes something the map draws calls
:func:`notify_map`. The event goes through the Channels layer to every socket
subscribed to that workspace, and the ``<brew-gis-map>`` component patches
itself in place, so nothing reloads the page.

Events are *invalidations*, not payloads. ``layers.changed`` makes the client
fetch the layer list again from ``map_layers_json`` and reconcile it, and
``tiles.changed`` makes it cache-bust the named tile sources. Celery workers
can therefore publish without a request to build absolute tile URLs from.

Each event is published on commit (``transaction.on_commit``), so a client
never re-fetches before the change is visible to its next request. Outside a
transaction (autocommit, a Celery task) on_commit runs immediately. Publishing
is best-effort (``robust=True``) because the data change has already committed
by then, and a client that misses an event resyncs fully when its socket
reconnects.

Event kinds (``kind`` in the JSON message):

- ``layers.changed`` — a Layer, LayerGroup or SymbologyConfig was saved or
  deleted (``signals.py``).
- ``tiles.changed`` — data under existing layers changed. ``scenario_id``
  names a scenario's canvas; ``layer_keys`` names specific layers; neither
  means every layer.
- ``paint.run`` / ``analysis.run`` / ``import.run`` — a background run changed
  status (``signals.py``).
- ``basemap.changed`` — the user picked a basemap. The choice is
  session-scoped, so this goes to that user's sockets only.
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def workspace_group(workspace_id: int) -> str:
    """Channels group every map socket on *workspace_id* joins."""
    return f"map.ws.{workspace_id}"


def user_group(workspace_id: int, user_id: int) -> str:
    """Channels group for one user's map sockets on *workspace_id*."""
    return f"map.ws.{workspace_id}.user.{user_id}"


def _publish(group: str, payload: dict[str, Any]) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        group, {"type": "map.event", "payload": payload}
    )


def notify_map(
    *, workspace_id: int, kind: str, user_id: int | None = None, **payload: Any
) -> None:
    """Publish a *kind* map event to *workspace_id*'s sockets once the transaction commits.

    With *user_id*, only that user's sockets receive it. *payload* must be
    JSON-serializable.
    """
    group = (
        workspace_group(workspace_id)
        if user_id is None
        else user_group(workspace_id, user_id)
    )
    message = {"kind": kind, **payload}
    transaction.on_commit(lambda: _publish(group, message), robust=True)
