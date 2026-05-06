from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render

from brewgis.workspace.models import Workspace


def home(request: HttpRequest) -> HttpResponse:
    workspaces = Workspace.objects.all()
    return render(request, "workspace/home.html", {"workspaces": workspaces})
