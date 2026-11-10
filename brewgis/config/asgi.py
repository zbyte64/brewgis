# ruff: noqa
"""
ASGI config for Brew GIS project.

HTTP is the WSGI application from ``wsgi.py`` run through ``WsgiToAsgi``, so
the tile-server proxy (``/martin/``) and ``ATOMIC_REQUESTS`` behave
exactly as they do under a WSGI server. Websockets go to the Channels
consumers in ``brewgis.workspace.routing``: the live map-event stream.

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

# Importing wsgi sets DJANGO_SETTINGS_MODULE and loads the app registry,
# which the routing import below needs.
from brewgis.config.wsgi import application as wsgi_application
from brewgis.workspace.routing import websocket_urlpatterns

_wsgi_http = WsgiToAsgi(wsgi_application)


async def http_application(scope, receive, send):
    """Serve one HTTP request through the WSGI app on a thread of its own."""
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
