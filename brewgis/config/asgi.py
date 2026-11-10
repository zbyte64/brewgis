# ruff: noqa
"""
ASGI config for Brew GIS project.

HTTP is the WSGI application from ``wsgi.py`` run through ``WsgiToAsgi``, so
the tile-server proxy (``/martin/``) and ``ATOMIC_REQUESTS`` behave
exactly as they do under a WSGI server. Websockets go to the Channels
consumers in ``brewgis.workspace.routing``: the live map-event stream.
``/sqlmesh/`` is served natively, logged-in users only, by ``sqlmesh_ui_proxy``.

Each HTTP request runs on its own thread, as under a threaded WSGI server.
``WsgiToAsgi`` calls the WSGI app through ``sync_to_async``, which outside a
``ThreadSensitiveContext`` puts every call on one process-wide thread — so a
tile Martin takes seconds to build, proxied through ``/martin/``, held up
every page, panel and form behind it. Django's own ASGI handler opens such a
context per request for the same reason.
"""

from asgiref.sync import ThreadSensitiveContext
from asgiref.wsgi import WsgiToAsgi
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from typing import TYPE_CHECKING
from typing import cast

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from collections.abc import Callable

# Importing wsgi sets DJANGO_SETTINGS_MODULE and loads the app registry,
# which the routing import below needs.
from brewgis.config.wsgi import application as wsgi_application
from brewgis.config.sqlmesh_ui_proxy import is_sqlmesh_ui_path
from brewgis.config.sqlmesh_ui_proxy import sqlmesh_ui_proxy
from brewgis.workspace.routing import websocket_urlpatterns

_wsgi_http = WsgiToAsgi(wsgi_application)
_sqlmesh_ui = cast(
    "Callable[..., Awaitable[None]]", AuthMiddlewareStack(sqlmesh_ui_proxy)
)  # channels types its middleware as ASGI2; this one is ASGI3.


async def http_application(scope, receive, send):
    """Serve one HTTP request through the WSGI app on a thread of its own."""
    if is_sqlmesh_ui_path(scope["path"]):
        await _sqlmesh_ui(scope, receive, send)
        return
    async with ThreadSensitiveContext():
        await _wsgi_http(scope, receive, send)


application = ProtocolTypeRouter(
    {
        "http": http_application,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
