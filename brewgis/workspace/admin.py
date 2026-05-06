from django.contrib import admin

# Register your models here.
from .models import Workspace


class WorkspaceAdmin(admin.ModelAdmin):
    pass


admin.site.register(Workspace, WorkspaceAdmin)
