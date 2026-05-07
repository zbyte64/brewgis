"""Unified import landing page view."""
from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.views.fetch_census import CensusFetchForm
from brewgis.workspace.views.fetch_employment import EmploymentFetchForm
from brewgis.workspace.views.fetch_poi import POIFetchForm
from brewgis.workspace.views.allocate_data import AllocateForm
from brewgis.workspace.views.stitch_data import StitchForm


@user_passes_test(lambda u: u.is_authenticated)
def import_center(request: HttpRequest) -> HttpResponse:
    """Render the unified import landing page with tabbed interface."""
    active_tab = request.GET.get("tab", "upload")

    # Recent imports
    recent_imports = DataImportRun.objects.select_related("workspace").order_by("-created_at")[:20]

    context = {
        "active_tab": active_tab,
        "workspaces": Workspace.objects.all(),
        "census_form": CensusFetchForm(),
        "employment_form": EmploymentFetchForm(),
        "poi_form": POIFetchForm(),
        "allocate_form": AllocateForm(),
        "stitch_form": StitchForm(),
        "recent_imports": recent_imports,
    }

    return render(request, "workspace/import_center.html", context)
