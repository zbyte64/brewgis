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

# daphne.server installs Twisted's asyncio reactor on import; it must be the
# first Twisted import in the process.
from daphne.server import Server  # isort:skip
from twisted.internet import reactor  # isort:skip

from channels.routing import get_default_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

_START_TIMEOUT_SECONDS = 10.0


class DaphneLiveServer:
    """Daphne on an ephemeral localhost port, running until :meth:`stop`."""

    def __init__(self) -> None:
        self._server = Server(
            application=ASGIStaticFilesHandler(get_default_application()),  # type: ignore[arg-type]
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

    def stop(self) -> None:
        # The reactor cannot be restarted, so this server is session-scoped.
        reactor.callFromThread(reactor.stop)  # type: ignore[attr-defined]
        self._thread.join(timeout=_START_TIMEOUT_SECONDS)
