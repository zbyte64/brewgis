# ruff: noqa
"""
ASGI config for Brew GIS project.

HTTP is the WSGI application from ``wsgi.py`` run through ``WsgiToAsgi``, so
the tile-server proxy (``/tipg/``, ``/martin/``) and ``ATOMIC_REQUESTS`` behave
exactly as they do under a WSGI server. Websockets go to the Channels
consumers in ``brewgis.workspace.routing``: the live map-event stream.
"""

from asgiref.wsgi import WsgiToAsgi
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

# Importing wsgi sets DJANGO_SETTINGS_MODULE and loads the app registry,
# which the routing import below needs.
from brewgis.config.wsgi import application as wsgi_application
from brewgis.workspace.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": WsgiToAsgi(wsgi_application),
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
