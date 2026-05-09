from django.contrib import admin

from brewgis.workspace.built_forms.admin import *  # noqa: F403

from .models import AnalysisRun
from .models import PaintConstraint
from .models import PaintedCanvas
from .models import Scenario
from .models import Workspace

# Register your models here.


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
