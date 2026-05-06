from django.shortcuts import render

from brewgis.workspace.models import Workspace


def home(request):
    workspaces = Workspace.objects.all()
    return render(request, "workspace/home.html", {"workspaces": workspaces})
