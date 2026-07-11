from django.contrib import admin

from brewgis.workspace.built_forms.admin import *  # noqa: F403

from .models import AnalysisRun
from .models import BuiltFormDefinition
from .models import DataSource
from .models import DataSourceCategory
from .models import PaintConstraint
from .models import PaintedCanvas
from .models import POICache
from .models import Scenario
from .models import Workspace

# Register your models here.


@admin.register(BuiltFormDefinition)
class BuiltFormDefinitionAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "name",
        "built_form_category",
        "du_per_acre",
        "intersection_density",
    )
    list_filter = ("built_form_category", "is_active")
    search_fields = ("key", "name")


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    pass


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "workspace",
        "scenario_type",
        "base_year",
        "horizon_year",
    )
    list_filter = ("workspace", "scenario_type")
    search_fields = ("name", "slug")


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    """Admin for AnalysisRun."""

    list_display = (
        "pk",
        "workspace",
        "status",
        "modules_summary",
        "started_at",
        "completed_at",
    )
    list_filter = ("status",)
    search_fields = ("workspace__name",)
    readonly_fields = ("started_at", "completed_at", "created_at")
    fieldsets = (
        ("Run", {"fields": ("workspace", "modules", "status", "vars")}),
        ("Timing", {"fields": ("started_at", "completed_at", "created_at")}),
        ("Errors", {"fields": ("error_log",)}),
    )

    @admin.display(description="Modules")
    def modules_summary(self, obj: AnalysisRun) -> str:
        return ", ".join(obj.modules) if obj.modules else "-"


@admin.register(PaintedCanvas)
class PaintedCanvasAdmin(admin.ModelAdmin):
    list_display = (
        "scenario",
        "feature_id",
        "column_name",
        "painted_value",
        "painted_by",
        "painted_at",
    )
    list_filter = ("scenario", "column_name")
    search_fields = ("feature_id",)


@admin.register(PaintConstraint)
class PaintConstraintAdmin(admin.ModelAdmin):
    list_display = ("workspace", "column", "operator", "value", "severity")
    list_filter = ("workspace", "column", "severity")
    search_fields = ("column",)


@admin.register(DataSourceCategory)
class DataSourceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order")
    list_editable = ("sort_order",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "provider",
        "acquisition_priority",
        "is_importable",
    )
    list_filter = (
        "category",
        "acquisition_priority",
        "is_importable",
        "data_format",
        "update_frequency",
    )
    search_fields = ("name", "provider", "description")
    list_editable = ("is_importable",)
    autocomplete_fields = ("category",)


@admin.register(POICache)
class POICacheAdmin(admin.ModelAdmin):
    list_display = ("workspace", "name", "source", "fetched_at")
    list_filter = ("name", "source", "workspace")
    search_fields = ("name",)
    raw_id_fields = ("workspace",)
