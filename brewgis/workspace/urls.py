from django.urls import path

from .views import CreateLayerView
from .views import ReadGISFileView
from .views import auto_generate
from .views import edit_symbology
from .views import home
from .views import preview_symbology
from .views import view_workspace_map
from .views import analysis_launch
from .views import analysis_list
from .views import analysis_status
from .views.built_forms import (
    BuildingTypeCreateView as building_type_create,  # noqa: N813
)
from .views.built_forms import (
    BuildingTypeDeleteView as building_type_delete,  # noqa: N813
)
from .views.built_forms import (
    BuildingTypeUpdateView as building_type_edit,  # noqa: N813
)
from .views.built_forms import PlaceTypeCreateView as place_type_create  # noqa: N813
from .views.built_forms import PlaceTypeDeleteView as place_type_delete  # noqa: N813
from .views.built_forms import PlaceTypeUpdateView as place_type_edit  # noqa: N813
from .views.built_forms import building_type_bake
from .views.built_forms import building_type_list
from .views.built_forms import place_type_bake
from .views.built_forms import place_type_list

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
    # Built Forms
    path(
        "built-forms/building-types/",
        building_type_list,
        name="building_type_list",
    ),
    path(
        "built-forms/building-types/create/",
        building_type_create.as_view(),
        name="building_type_create",
    ),
    path(
        "built-forms/building-types/<int:pk>/edit/",
        building_type_edit.as_view(),
        name="building_type_edit",
    ),
    path(
        "built-forms/building-types/<int:pk>/delete/",
        building_type_delete.as_view(),
        name="building_type_delete",
    ),
    path(
        "built-forms/building-types/<int:pk>/bake/",
        building_type_bake,
        name="building_type_bake",
    ),
    path(
        "built-forms/place-types/",
        place_type_list,
        name="place_type_list",
    ),
    path(
        "built-forms/place-types/create/",
        place_type_create.as_view(),
        name="place_type_create",
    ),
    path(
        "built-forms/place-types/<int:pk>/edit/",
        place_type_edit.as_view(),
        name="place_type_edit",
    ),
    path(
        "built-forms/place-types/<int:pk>/delete/",
        place_type_delete.as_view(),
        name="place_type_delete",
    ),
    path(
        "built-forms/place-types/<int:pk>/bake/",
        place_type_bake,
        name="place_type_bake",
    ),
    # Analysis Pipeline
    path("analysis/launch/", analysis_launch.as_view(), name="analysis_launch"),
    path("analysis/runs/", analysis_list, name="analysis_list"),
    path("analysis/runs/<int:run_pk>/", analysis_status, name="analysis_status"),
]
