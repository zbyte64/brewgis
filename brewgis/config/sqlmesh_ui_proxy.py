"""Serve the SQLMesh UI at ``/sqlmesh/`` to logged-in Django users.

``sqlmesh ui`` (compose/django/start-sqlmesh-ui) has no login of its own, so
this proxy is the only way in. It refuses anonymous requests, forwards the rest
to ``SQLMESH_UI_UPSTREAM_URL`` and never sends the Django session cookie
upstream.

Three things the UI needs that a plain forwarder does not give:

- Its ``index.html`` uses absolute asset paths and it reads its base path from
  ``window.__BASE_URL__``, so the HTML shell is rewritten to live under
  ``/sqlmesh``. The client prefixes every API call with that base path itself.
- ``/api/events`` is a server-sent-events stream, so responses are streamed and
  the upstream request ends when the browser tab closes.
- The UI mounts every API endpoint in every ``--mode`` and ``--mode`` only
  changes what the UI shows. When ``SQLMESH_UI_MODE`` is ``catalog`` or ``docs``
  the proxy therefore also refuses every non-GET request, the ``/api/commands/``
  endpoints and ``/api/table_diff``, which are the ones that run SQL.

The UI's Vite build also emits ``modulepreload`` links at the root path
(``/assets/X.js``). Those 404 here and are harmless: only CSS preloads can break
the page, and the build has no CSS assets. The real ``import()`` calls resolve
relative to ``/sqlmesh/assets/``.

This is a raw ASGI app rather than WSGI middleware because it rewrites HTML and
streams SSE, and it must not hold a worker thread or the ``ATOMIC_REQUESTS``
transaction open for the lifetime of a stream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import resolve_url

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable
    from collections.abc import MutableMapping

    Scope = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[dict[str, Any]]]
    Send = Callable[[dict[str, Any]], Awaitable[None]]

SQLMESH_UI_PREFIX = "/sqlmesh"
_READ_ONLY_MODES = frozenset({"catalog", "docs"})
_HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)
_DROPPED_REQUEST_HEADERS = _HOP_BY_HOP | {
    b"host",
    b"cookie",
    b"accept-encoding",
    b"content-length",
}
# read=None keeps the /api/events stream open for as long as the tab is.
_TIMEOUT = httpx.Timeout(10.0, read=None)

logger = logging.getLogger(__name__)


def is_sqlmesh_ui_path(path: str) -> bool:
    """Whether *path* belongs to the SQLMesh UI."""
    return path == SQLMESH_UI_PREFIX or path.startswith(SQLMESH_UI_PREFIX + "/")


def _rewrite_index(html: bytes) -> bytes:
    """Move the UI's root-relative asset paths and base URL under ``/sqlmesh``."""
    text = html.decode("utf-8")
    text = text.replace('href="/', f'href="{SQLMESH_UI_PREFIX}/')
    text = text.replace('src="/', f'src="{SQLMESH_UI_PREFIX}/')
    base_script = f'<script>window.__BASE_URL__ = "{SQLMESH_UI_PREFIX}";</script>'
    text = text.replace("</head>", base_script + "</head>", 1)
    return text.encode("utf-8")


async def _respond(
    send: Send,
    status: int,
    body: bytes,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                *(headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive: Receive) -> bytes | None:
    """Return the whole request body, or ``None`` if the client disconnected."""
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _wait_for_disconnect(receive: Receive) -> None:
    while (await receive())["type"] != "http.disconnect":
        pass


async def _relay(upstream: httpx.Response, send: Send) -> None:
    """Send the upstream response to the browser, rewriting the HTML shell."""
    headers = [
        (k.lower(), v) for k, v in upstream.headers.raw if k.lower() not in _HOP_BY_HOP
    ]
    if upstream.headers.get("content-type", "").startswith("text/html"):
        body = _rewrite_index(await upstream.aread())
        headers = [(k, v) for k, v in headers if k != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send(
            {
                "type": "http.response.start",
                "status": upstream.status_code,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})
        return

    await send(
        {
            "type": "http.response.start",
            "status": upstream.status_code,
            "headers": headers,
        }
    )
    async for chunk in upstream.aiter_raw():
        await send({"type": "http.response.body", "body": chunk, "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})


async def sqlmesh_ui_proxy(scope: Scope, receive: Receive, send: Send) -> None:
    """Serve one request to the SQLMesh UI. Needs ``scope["user"]`` from auth."""
    raw_path = scope.get("raw_path")
    path = raw_path.decode("latin-1") if raw_path else quote(scope["path"])
    upstream_path = path[len(SQLMESH_UI_PREFIX) :] or "/"
    query = scope.get("query_string", b"").decode("latin-1")
    query_suffix = f"?{query}" if query else ""

    if not scope["user"].is_authenticated:
        if upstream_path.startswith("/api/"):
            await _respond(send, 401, b"Log in to use the SQLMesh UI.")
            return
        next_path = scope["path"] + query_suffix
        location = (
            f"{resolve_url(settings.LOGIN_URL)}"
            f"?{urlencode({REDIRECT_FIELD_NAME: next_path})}"
        )
        await _respond(send, 302, b"", [(b"location", location.encode("latin-1"))])
        return

    if settings.SQLMESH_UI_MODE in _READ_ONLY_MODES and (
        scope["method"] not in ("GET", "HEAD")
        or upstream_path.startswith(("/api/commands/", "/api/table_diff"))
    ):
        await _respond(send, 403, b"The SQLMesh UI is read-only on this server.")
        return

    body = await _read_body(receive)
    if body is None:
        return

    url = settings.SQLMESH_UI_UPSTREAM_URL.rstrip("/") + upstream_path + query_suffix
    # Identity encoding keeps the HTML rewrite and aiter_raw free of compressed bytes.
    headers = [
        (k, v) for k, v in scope["headers"] if k.lower() not in _DROPPED_REQUEST_HEADERS
    ]
    headers.append((b"accept-encoding", b"identity"))

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            upstream = await client.send(
                client.build_request(
                    scope["method"], url, headers=headers, content=body
                ),
                stream=True,
            )
        except httpx.TransportError:
            logger.warning("SQLMesh UI at %s is unreachable", url, exc_info=True)
            await _respond(send, 502, b"The SQLMesh UI is not reachable.")
            return

        try:
            relay = asyncio.create_task(_relay(upstream, send))
            disconnect = asyncio.create_task(_wait_for_disconnect(receive))
            done, pending = await asyncio.wait(
                {relay, disconnect}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        finally:
            await upstream.aclose()
