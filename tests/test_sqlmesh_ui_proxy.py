"""The ``/sqlmesh/`` proxy (``brewgis/config/sqlmesh_ui_proxy.py``).

``sqlmesh ui`` has no login of its own, so the proxy must refuse anonymous
requests, keep the Django session cookie away from the UI, and stop a
catalog-mode server from running SQL through the UI's API.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlsplit

import pytest
from channels.testing import HttpCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

from brewgis.config.asgi import application
from brewgis.config.sqlmesh_ui_proxy import is_sqlmesh_ui_path

if TYPE_CHECKING:
    from collections.abc import Iterator

HTML_SHELL = (
    b'<html><head><link rel="icon" href="/favicon.ico">'
    b'<script type="module" src="/assets/app.js"></script></head><body></body></html>'
)


class _UpstreamHandler(BaseHTTPRequestHandler):
    """A stand-in ``sqlmesh ui`` that records every request it receives."""

    seen: list[dict[str, Any]]

    def do_GET(self) -> None:
        self._answer(b"")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self._answer(self.rfile.read(length))

    def _answer(self, body: bytes) -> None:
        self.seen.append(
            {
                "method": self.command,
                "path": self.path,
                "cookie": self.headers.get("Cookie"),
                "accept_encoding": self.headers.get("Accept-Encoding"),
                "body": body,
            }
        )
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", HTML_SHELL)
        else:
            self._send(
                200, "application/json", json.dumps({"path": self.path}).encode()
            )

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


@pytest.fixture
def upstream(settings) -> Iterator[list[dict[str, Any]]]:
    """Point the proxy at a stub UI in ``ide`` mode; yield the requests it saw."""
    seen: list[dict[str, Any]] = []
    handler = type("Handler", (_UpstreamHandler,), {"seen": seen})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings.SQLMESH_UI_UPSTREAM_URL = f"http://127.0.0.1:{server.server_port}"
    settings.SQLMESH_UI_MODE = "ide"
    try:
        yield seen
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def session_cookie() -> str:
    user = get_user_model().objects.create_user(username="planner")
    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


async def _request(
    method: str,
    path: str,
    *,
    cookie: str | None = None,
    body: bytes = b"",
) -> dict[str, Any]:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()))
    communicator = HttpCommunicator(
        application, method, path, body=body, headers=headers
    )
    response = await communicator.get_response(timeout=10)
    return dict(response)


def _header(response: dict[str, Any], name: str) -> str:
    for key, value in response["headers"]:
        if key.lower() == name.encode():
            return value.decode("latin-1")
    msg = f"response has no {name} header"
    raise AssertionError(msg)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/sqlmesh", True),
        ("/sqlmesh/", True),
        ("/sqlmesh/api/models", True),
        ("/sqlmesh-other/", False),
        ("/martin/some.source", False),
    ],
)
def test_only_sqlmesh_paths_reach_the_proxy(path: str, *, expected: bool) -> None:
    assert is_sqlmesh_ui_path(path) is expected


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_anonymous_page_request_is_sent_to_login(upstream) -> None:
    response = await _request("GET", "/sqlmesh/")

    assert response["status"] == 302
    location = urlsplit(_header(response, "location"))
    assert parse_qs(location.query)["next"] == ["/sqlmesh/"]
    assert upstream == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_anonymous_api_request_is_refused(upstream) -> None:
    response = await _request("GET", "/sqlmesh/api/meta")

    assert response["status"] == 401
    assert upstream == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_logged_in_html_shell_is_rewritten_under_the_prefix(
    upstream, session_cookie
) -> None:
    response = await _request("GET", "/sqlmesh/", cookie=session_cookie)
    body = response["body"].decode()

    assert response["status"] == 200
    assert 'href="/sqlmesh/favicon.ico"' in body
    assert 'src="/sqlmesh/assets/app.js"' in body
    assert 'window.__BASE_URL__ = "/sqlmesh"' in body
    assert upstream[0]["path"] == "/"
    assert upstream[0]["accept_encoding"] == "identity"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_session_cookie_never_reaches_the_ui(upstream, session_cookie) -> None:
    await _request("GET", "/sqlmesh/api/meta", cookie=session_cookie)

    assert upstream[0]["cookie"] is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_query_string_is_forwarded(upstream, session_cookie) -> None:
    response = await _request("GET", "/sqlmesh/api/models?x=1", cookie=session_cookie)

    assert json.loads(response["body"]) == {"path": "/api/models?x=1"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_ide_mode_forwards_writes(upstream, session_cookie, settings) -> None:
    settings.SQLMESH_UI_MODE = "ide"

    response = await _request(
        "POST",
        "/sqlmesh/api/plan",
        cookie=session_cookie,
        body=b'{"environment":"dev"}',
    )

    assert response["status"] == 200
    assert upstream[0]["method"] == "POST"
    assert upstream[0]["body"] == b'{"environment":"dev"}'


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["catalog", "docs"])
async def test_read_only_modes_refuse_writes(
    upstream, session_cookie, settings, mode
) -> None:
    settings.SQLMESH_UI_MODE = mode

    response = await _request(
        "POST", "/sqlmesh/api/plan", cookie=session_cookie, body=b"{}"
    )

    assert response["status"] == 403
    assert upstream == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "path", ["/sqlmesh/api/commands/render", "/sqlmesh/api/table_diff"]
)
async def test_read_only_modes_refuse_sql_running_endpoints(
    upstream, session_cookie, settings, path
) -> None:
    settings.SQLMESH_UI_MODE = "catalog"

    response = await _request("GET", path, cookie=session_cookie)

    assert response["status"] == 403
    assert upstream == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_unreachable_ui_is_a_bad_gateway(settings, session_cookie) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    settings.SQLMESH_UI_UPSTREAM_URL = f"http://127.0.0.1:{closed_port}"

    response = await _request("GET", "/sqlmesh/", cookie=session_cookie)

    assert response["status"] == 502
