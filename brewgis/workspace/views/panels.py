"""Panel-aware view wrappers for the map-centric shell.

These views return partial HTML suitable for injecting into
the right panel, bottom sheet, or left sidebar of the
WYSIWYG map shell. They delegate to existing views and
force ``panel=1`` rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse


def is_panel_request(request: HttpRequest) -> bool:
    """Detect whether the request is for a panel fragment.

    Returns ``True`` when the request came from htmx (``HX-Request`` header)
    or carries the ``?panel=1`` query parameter.
    """
    return (
        request.GET.get("panel") == "1" or request.headers.get("HX-Request") == "true"
    )


# ---------------------------------------------------------------------------
# Left-sidebar panel endpoints
# ---------------------------------------------------------------------------


@user_passes_test(lambda u: u.is_authenticated)
def panel_layer_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return the layer list panel content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    # Check for active scenario (passed via query param when on workspace map)
    scenario: Scenario | None = None
    scenario_id = request.GET.get("scenario")
    if scenario_id:
        scenario = get_object_or_404(Scenario, pk=int(scenario_id), workspace=workspace)

    context: dict[str, object] = {
        "workspace": workspace,
        "scenario": scenario,
        "is_public_view": False,
    }
    return render(
        request,
        "workspace/partials/_layer_list_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_data_catalog(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return data catalog content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context: dict[str, object] = {
        "workspace": workspace,
    }
    return render(
        request,
        "workspace/partials/_catalog_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_import_center(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return import center content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context: dict[str, object] = {
        "workspace": workspace,
    }
    return render(
        request,
        "workspace/partials/_import_panel.html",
        context,
    )


@user_passes_test(lambda u: u.is_authenticated)
def panel_analysis_launch(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return analysis launch content for the left sidebar."""
    from brewgis.workspace.views.analysis import AnalysisLaunchView

    view = AnalysisLaunchView.as_view()
    return view(request, workspace_pk=workspace_pk)


@user_passes_test(lambda u: u.is_authenticated)
def panel_report_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return report list content for the left sidebar."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context: dict[str, object] = {
        "workspace": workspace,
    }
    return render(
        request,
        "workspace/partials/_report_list_panel.html",
        context,
    )
