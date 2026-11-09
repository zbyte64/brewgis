"""The ``/martin/`` tile proxy (``brewgis/config/wsgi.py``).

Martin writes absolute tile URLs into every TileJSON it serves, built from the
Host header of the request it receives. The proxy used to send a fixed
``Host: localhost:8000``, so a site served under any other name handed the
browser tile URLs on ``localhost:8000`` — which the browser fetched from its
own machine and refused as cross-origin, and the map drew no tiles.
"""

from __future__ import annotations

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING
from typing import Any

import pytest
from werkzeug.test import Client

from brewgis.config import wsgi

if TYPE_CHECKING:
    from collections.abc import Iterator


class _EchoHostHandler(BaseHTTPRequestHandler):
    """A stand-in tile server that answers with the Host header it was sent."""

    def do_GET(self) -> None:
        body = json.dumps({"host": self.headers["Host"], "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


@pytest.fixture
def proxy(settings) -> Iterator[Client]:
    """The WSGI application, proxying ``/martin/`` to the echo server."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHostHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_url = settings.TILE_SERVER_MARTIN_URL
    settings.TILE_SERVER_MARTIN_URL = f"http://127.0.0.1:{server.server_port}"
    try:
        yield Client(importlib.reload(wsgi).application)
    finally:
        server.shutdown()
        server.server_close()
        # Rebuilt with the real tile server before the settings fixture's own
        # teardown, so no later test inherits a proxy to the stopped stub.
        settings.TILE_SERVER_MARTIN_URL = original_url
        importlib.reload(wsgi)


@pytest.mark.parametrize("host", ["brewgis.example.org", "localhost:8000"])
def test_tile_server_sees_the_host_the_browser_asked_for(proxy, host) -> None:
    response = proxy.get("/martin/some.source", headers={"Host": host})

    assert response.status_code == 200
    assert json.loads(response.get_data()) == {"host": host, "path": "/some.source"}
