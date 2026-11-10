"""A live test server that speaks ASGI, so browser tests get websockets.

pytest-django's ``live_server`` runs Django's WSGI ``LiveServerThread``, which
cannot accept the map page's event websocket (``/ws/workspace/<pk>/map/``).
:class:`DaphneLiveServer` serves the project's ASGI application
(``brewgis.config.asgi``, the same router production runs) from Daphne on a
background thread instead. Because it runs in the test process, like
``LiveServerThread``, the server sees the test database, the session's settings
overrides and the in-memory channel layer, so a view's map event reaches a
browser's socket.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

# daphne.server installs Twisted's asyncio reactor on import; it must be the
# first Twisted import in the process.
from daphne.server import Server  # isort:skip
from twisted.internet import reactor  # isort:skip

from channels.routing import get_default_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable

_START_TIMEOUT_SECONDS = 10.0
_DRAIN_POLL_SECONDS = 0.05


class _InFlightCounter:
    """ASGI wrapper counting the HTTP requests the server has not finished.

    Counted from the moment Daphne hands a request over, including while it
    waits for its thread and while it runs middleware outside any database
    transaction — the windows in which the request is invisible to
    ``pg_stat_activity``.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app
        self.in_flight = 0

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Only the reactor's event loop touches the count; other threads read it.
        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1


class DaphneLiveServer:
    """Daphne on an ephemeral localhost port, running until :meth:`stop`."""

    def __init__(self) -> None:
        self._requests = _InFlightCounter(
            ASGIStaticFilesHandler(get_default_application())  # type: ignore[arg-type]
        )
        self._server = Server(
            application=self._requests,  # type: ignore[arg-type]
            endpoints=["tcp:port=0:interface=127.0.0.1"],
            signal_handlers=False,
        )
        self._thread = threading.Thread(
            target=self._server.run, name="daphne-live-server", daemon=True
        )
        self._thread.start()

        deadline = time.monotonic() + _START_TIMEOUT_SECONDS
        while not self._server.listening_addresses:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                msg = "Daphne live server did not start listening"
                raise RuntimeError(msg)
            time.sleep(0.05)
        _host, self.port = self._server.listening_addresses[0]

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def __str__(self) -> str:
        return self.url

    def wait_until_idle(self, timeout: float) -> int:
        """Block until no HTTP request is in flight; return how many still are."""
        deadline = time.monotonic() + timeout
        while self._requests.in_flight and time.monotonic() < deadline:
            time.sleep(_DRAIN_POLL_SECONDS)
        return self._requests.in_flight

    def stop(self) -> None:
        # A request still running when the reactor stops never returns: its
        # WSGI thread waits forever on the stopped event loop, and the
        # interpreter's exit joins that thread, so pytest would never exit.
        self.wait_until_idle(_START_TIMEOUT_SECONDS)
        # The reactor cannot be restarted, so this server is session-scoped.
        reactor.callFromThread(reactor.stop)  # type: ignore[attr-defined]
        self._thread.join(timeout=_START_TIMEOUT_SECONDS)
