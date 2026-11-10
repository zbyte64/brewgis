"""Tests for the ASGI entrypoint's HTTP handling (``brewgis.config.asgi``).

Daphne serves every HTTP request through the WSGI app. Run bare through
``WsgiToAsgi``, those requests share one process-wide thread, so a tile that
Martin takes seconds to build, proxied through ``/martin/``, held up every
other page until it finished.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest
from asgiref.wsgi import WsgiToAsgi

from brewgis.config import asgi

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable


def _scope(path: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver")],
        "server": ("testserver", 80),
    }


async def _get(path: str) -> bytes:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await asgi.http_application(_scope(path), receive, send)
    return b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )


@pytest.mark.asyncio
async def test_a_slow_request_does_not_hold_up_others(monkeypatch) -> None:
    slow_started = threading.Event()
    release_slow = threading.Event()

    def wsgi_app(environ: dict, start_response: Callable) -> Iterable[bytes]:
        if environ["PATH_INFO"] == "/slow":
            slow_started.set()
            release_slow.wait(timeout=10)
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [environ["PATH_INFO"].encode()]

    monkeypatch.setattr(asgi, "_wsgi_http", WsgiToAsgi(wsgi_app))

    slow = asyncio.create_task(_get("/slow"))
    try:
        # The slow request holds its thread before the fast one is sent.
        assert await asyncio.to_thread(slow_started.wait, 5)
        fast = await asyncio.wait_for(_get("/fast"), timeout=5)
        assert not slow.done()
    finally:
        release_slow.set()
    await asyncio.wait_for(slow, timeout=5)

    assert fast == b"/fast"
