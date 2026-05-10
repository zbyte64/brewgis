from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render

from brewgis.workspace.models import County
from brewgis.workspace.models import Workspace


def _home(request: HttpRequest) -> HttpResponse:
    workspaces = Workspace.objects.all().prefetch_related("analysis_runs", "layers")
    workspace_data = []
    for ws in workspaces:
        layer_count = ws.layers.count()
        county_names = []
        for entry in ws.county_fips_list:
            if isinstance(entry, dict):
                state_fips = entry.get("state", "")
                county_fips = entry.get("county", "")
            else:
                state_fips = str(entry)
                county_fips = ""
            c = County.objects.filter(
                state_fips=state_fips,
                county_fips=county_fips,
            ).first()
            if c:
                county_names.append(c.name)
        last_run = ws.analysis_runs.order_by("-created_at").first()
        workspace_data.append(
            {
                "workspace": ws,
                "layer_count": layer_count,
                "county_names": county_names,
                "last_run_status": last_run.status if last_run else None,
            }
        )
    return render(
        request,
        "workspace/home.html",
        {"workspaces_data": workspace_data, "workspaces": workspaces},
    )


home = user_passes_test(lambda u: u.is_authenticated)(_home)
