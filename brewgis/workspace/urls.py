from django.urls import path

from .views import CreateLayerView
from .views import ReadGISFileView
from .views import allocate
from .views import analysis_launch
from .views import analysis_list
from .views import analysis_status
from .views import auto_generate
from .views import census_fetch
from .views import census_preview
from .views import check_prerequisites
from .views import clear_paint
from .views import county_options
from .views import edit_symbology
from .views import employment_fetch
from .views import employment_preview
from .views import home
from .views import import_center
from .views import import_status
from .views import layer_legend
from .views import merge_paint_edits
from .views import paint_built_form
from .views import paint_features
from .views import paint_history
from .views import poi_fetch
from .views import preview_symbology
from .views import scenario_clone
from .views import scenario_comparison
from .views import scenario_comparison_data
from .views import scenario_create
from .views import scenario_delete
from .views import scenario_edit
from .views import stitch
from .views import undo_paint
from .views import view_workspace_map
from .views import workspace_create
from .views import workspace_detail
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
from .views.report import generate_map_report  # noqa: F811
from .views.report import generate_paint_report  # noqa: F811
from .views.report import generate_scenario_report  # noqa: F811
from .views.report import report_detail  # noqa: F811
from .views.report import report_list  # noqa: F811
from .views.report import report_list_partial  # noqa: F811
from .views.token_auth import token_auth  # noqa: N813
from .views.report import report_status  # noqa: F811
from .views.filter import layer_filter_list  # noqa: N813
from .views.filter import layer_filter_create  # noqa: N813
from .views.filter import layer_filter_edit  # noqa: N813
from .views.filter import layer_filter_delete  # noqa: N813
from .views.filter import layer_filter_toggle  # noqa: N813
from .views.filter import layer_filter_preview  # noqa: N813
from .views.external_services import external_service_list  # noqa: N813
from .views.external_services import external_service_add  # noqa: N813
from .views.external_services import external_service_toggle  # noqa: N813
from .views.external_services import external_service_delete  # noqa: N813
from .views.basemaps import basemap_list  # noqa: N813
from .views.basemaps import basemap_select  # noqa: N813
from .views.layer_groups import layer_group_list  # noqa: N813
from .views.layer_groups import layer_group_create  # noqa: N813
from .views.layer_groups import layer_group_edit  # noqa: N813
from .views.layer_groups import layer_group_delete  # noqa: N813
from .views.layer_groups import layer_group_move_layer  # noqa: N813
from .views.data_table import layer_data_table  # noqa: N813

app_name = "workspace"
urlpatterns = [
    path("", home, name="home"),
    path("token-auth/", token_auth, name="token_auth"),
    path("new/", workspace_create.as_view(), name="workspace_create"),
    path("new/county-options/", county_options, name="county_options"),
    path("upload/", ReadGISFileView.as_view(), name="upload"),
    path("layers/create/", CreateLayerView.as_view(), name="create_layer"),
    path("<int:workspace_pk>/map/", view_workspace_map, name="workspace_map"),
    path("<int:pk>/", workspace_detail, name="workspace_detail"),
    # Scenario Management
    path(
        "<int:workspace_pk>/scenario/create/",
        scenario_create,
        name="scenario_create",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/edit/",
        scenario_edit,
        name="scenario_edit",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/delete/",
        scenario_delete,
        name="scenario_delete",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/clone/",
        scenario_clone,
        name="scenario_clone",
    ),
    path(
        "<int:workspace_pk>/scenarios/compare/",
        scenario_comparison,
        name="scenario_comparison",
    ),
    path(
        "<int:workspace_pk>/scenarios/compare/data/",
        scenario_comparison_data,
        name="scenario_comparison_data",
    ),
    # Paint Operations
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/paint/",
        paint_features,
        name="paint_features",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/paint-bf/",
        paint_built_form,
        name="paint_built_form",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/clear-paint/",
        clear_paint,
        name="clear_paint",
    ),
    # Paint History & Undo
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/paint-history/",
        paint_history,
        name="paint_history",
    ),
    path(
        "<int:workspace_pk>/scenario/<int:scenario_pk>/paint/undo/",
        undo_paint,
        name="undo_paint",
    ),
    # Merge Paint Edits between scenarios
    path(
        "<int:workspace_pk>/scenario/<int:source_pk>/merge/<int:target_pk>/",
        merge_paint_edits,
        name="merge_paint_edits",
    ),
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
    path(
        "symbology/<int:layer_pk>/legend/",
        layer_legend,
        name="layer_legend",
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
    path(
        "analysis/check-prerequisites/",
        check_prerequisites,
        name="check_prerequisites",
    ),
    # Import Center
    path("import/", import_center, name="import_center"),
    path("import/census/", census_fetch.as_view(), name="census_fetch"),
    path("import/census/preview/", census_preview, name="census_preview"),
    path(
        "import/employment/",
        employment_fetch.as_view(),
        name="employment_fetch",
    ),
    path(
        "import/employment/preview/",
        employment_preview,
        name="employment_preview",
    ),
    path("import/poi/", poi_fetch.as_view(), name="poi_fetch"),
    path("import/allocate/", allocate.as_view(), name="allocate"),
    path("import/stitch/", stitch.as_view(), name="stitch"),
    path("import/status/<int:run_pk>/", import_status, name="import_status"),
    # Report URLs (Phase 7b, 7f)
    path(
        "<int:workspace_pk>/reports/",
        report_list,
        name="report_list",
    ),
    path(
        "<int:workspace_pk>/reports/<int:report_pk>/",
        report_detail,
        name="report_detail",
    ),
    path(
        "<int:workspace_pk>/reports/<int:report_pk>/status/",
        report_status,
        name="report_status",
    ),
    path(
        "<int:workspace_pk>/reports/generate/scenario/",
        generate_scenario_report,
        name="generate_scenario_report",
    ),
    path(
        "<int:workspace_pk>/reports/generate/paint/",
        generate_paint_report,
        name="generate_paint_report",
    ),
    path(
        "<int:workspace_pk>/reports/generate/map/",
        generate_map_report,
        name="generate_map_report",
    ),
    path(
        "<int:workspace_pk>/reports/partial/",
        report_list_partial,
        name="report_list_partial",
    ),
    # Filter URLs (Phase 7d — Data Filtering UI)
    path(
        "filters/layer/<int:layer_pk>/",
        layer_filter_list,
        name="layer_filter_list",
    ),
    path(
        "filters/layer/<int:layer_pk>/create/",
        layer_filter_create,
        name="layer_filter_create",
    ),
    path(
        "filters/<int:pk>/edit/",
        layer_filter_edit,
        name="layer_filter_edit",
    ),
    path(
        "filters/<int:pk>/delete/",
        layer_filter_delete,
        name="layer_filter_delete",
    ),
    path(
        "filters/<int:pk>/toggle/",
        layer_filter_toggle,
        name="layer_filter_toggle",
    ),
    path(
        "filters/<int:pk>/preview/",
        layer_filter_preview,
        name="layer_filter_preview",
    ),
    # External Map Services
    path(
        "<int:workspace_pk>/external-services/",
        external_service_list,
        name="external_service_list",
    ),
    path(
        "<int:workspace_pk>/external-services/add/",
        external_service_add,
        name="external_service_add",
    ),
    path(
        "external-services/<int:pk>/toggle/",
        external_service_toggle,
        name="external_service_toggle",
    ),
    path(
        "external-services/<int:pk>/delete/",
        external_service_delete,
        name="external_service_delete",
    ),
    # Basemaps
    path(
        "basemaps/",
        basemap_list,
        name="basemap_list",
    ),
    path(
        "<int:workspace_pk>/basemaps/select/",
        basemap_select,
        name="basemap_select",
    ),
    # Layer Groups
    path(
        "<int:workspace_pk>/layer-groups/",
        layer_group_list,
        name="layer_group_list",
    ),
    path(
        "<int:workspace_pk>/layer-groups/create/",
        layer_group_create,
        name="layer_group_create",
    ),
    path(
        "layer-groups/<int:pk>/edit/",
        layer_group_edit,
        name="layer_group_edit",
    ),
    path(
        "layer-groups/<int:pk>/delete/",
        layer_group_delete,
        name="layer_group_delete",
    ),
    path(
        "layers/<int:layer_pk>/move-group/",
        layer_group_move_layer,
        name="layer_group_move_layer",
    ),
    # Data Table
    path(
        "layers/<int:layer_pk>/data/",
        layer_data_table,
        name="layer_data_table",
    ),
]
