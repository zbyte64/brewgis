from django.urls import path

from .views import CreateLayerView
from .views import ReadGISFileView
from .views import home
from .views import view_workspace_map
from .views import auto_generate
from .views import edit_symbology
from .views import preview_symbology

app_name = "workspace"
urlpatterns = [
    path("", home, name="home"),
    path("upload/", ReadGISFileView.as_view(), name="upload"),
    path("layers/create/", CreateLayerView.as_view(), name="create_layer"),
    path("<int:workspace_pk>/map/", view_workspace_map, name="workspace_map"),
    path(
        "symbology/<int:layer_pk>/edit/",
        edit_symbology,
        name="symbology_edit",
    ),
    path(
        "symbology/<int:layer_pk>/auto/",
        auto_generate,
        name="symbology_auto",
    ),
    path(
        "symbology/<int:layer_pk>/preview/",
        preview_symbology,
        name="symbology_preview",
    ),
]
