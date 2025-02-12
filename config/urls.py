# ruff: noqa
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views

from django.urls import path 
from django.contrib.auth.models import User
from brewgis.workspace.models import Layer, Scenario, ScenarioLayer, Workspace
from viewflow.contrib.auth import AuthViewset
from viewflow.contrib.admin import Admin
from viewflow.urls import Application, Site, ModelViewset

from brewgis.workspace.viewsets import ImportDataViewset, CreateLayerViewset, ScenarioModelViewSet


site = Site(title="ACME Corp", viewsets=[
    Application(
        title='Administration', icon='people', app_name='admin_dashboard', viewsets=[
            ModelViewset(model=User),
            Admin(),
            AuthViewset(with_profile_view=False),
            # from viewflow.workflow.flow import FlowAppViewset
        ]
    ),
    Application(
        title='GIS Workspace', icon='people', app_name='gis_workspace', viewsets=[
            ImportDataViewset(),
            CreateLayerViewset(),
            ModelViewset(model=Workspace),
            ScenarioModelViewSet(),
            ModelViewset(model=Layer),
            ModelViewset(model=ScenarioLayer),
        ]
    ),
])


urlpatterns = [
    path('', site.urls),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("accounts/", include("allauth.urls")),
    # Your stuff: custom urls includes go here
    # ...
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
