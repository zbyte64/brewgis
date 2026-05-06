from django.urls import path

from .views import CreateLayerView
from .views import ReadGISFileView
from .views import home
from .views import view_workspace_map

app_name = "workspace"
urlpatterns = [
    path("", home, name="home"),
    path("upload/", ReadGISFileView.as_view(), name="upload"),
    path("layers/create/", CreateLayerView.as_view(), name="create_layer"),
    path("<int:workspace_pk>/map/", view_workspace_map, name="workspace_map"),
]
