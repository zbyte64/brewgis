from django.contrib import admin
from brewgis.workspace.built_forms.admin import *  # noqa: F401,F403

# Register your models here.
from .models import Workspace
from .models import AnalysisRun


class WorkspaceAdmin(admin.ModelAdmin):
    pass


admin.site.register(Workspace, WorkspaceAdmin)

@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    """Admin for AnalysisRun."""

    list_display = ("pk", "workspace", "status", "modules_summary", "started_at", "completed_at")
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
