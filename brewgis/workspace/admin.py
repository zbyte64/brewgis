from django.contrib import admin
from brewgis.workspace.built_forms.admin import *  # noqa: F401,F403

# Register your models here.
from .models import Workspace


class WorkspaceAdmin(admin.ModelAdmin):
    pass


admin.site.register(Workspace, WorkspaceAdmin)
