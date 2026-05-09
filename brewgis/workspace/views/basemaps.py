"""Basemap selection views for BrewGIS.

Provides htmx-based endpoints for listing and selecting basemaps
for workspace map rendering.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from brewgis.workspace.models import Basemap

logger = logging.getLogger(__name__)

# Session key template: ws_{workspace_pk}_basemap_id
_SESSION_KEY = "ws_{}_basemap_id"


def _get_selected_basemap_id(request: HttpRequest, workspace_pk: int) -> int | None:
    """Return the selected basemap ID for a workspace from session."""
    return request.session.get(_SESSION_KEY.format(workspace_pk))


def _set_selected_basemap_id(
    request: HttpRequest, workspace_pk: int, basemap_id: int
) -> None:
    """Store the selected basemap ID for a workspace in session."""
    request.session[_SESSION_KEY.format(workspace_pk)] = basemap_id


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def basemap_list(request: HttpRequest) -> HttpResponse:
    """Return HTML partial listing all available basemaps with selection UI.

    Accepts optional query parameters:
    - workspace: workspace pk for session-based selection lookup
    - selected: explicit basemap id to highlight as selected
    """
    basemaps = Basemap.objects.all().order_by("sort_order")

    workspace_pk: int | None = None
    raw_ws = request.GET.get("workspace")
    if raw_ws:
        try:
            workspace_pk = int(raw_ws)
        except (ValueError, TypeError):
            pass

    selected_id: int | None = None
    raw_sel = request.GET.get("selected")
    if raw_sel:
        try:
            selected_id = int(raw_sel)
        except (ValueError, TypeError):
            pass

    # Prefer explicit selected param, fall back to session value
    if selected_id is None and workspace_pk is not None:
        selected_id = _get_selected_basemap_id(request, workspace_pk)

    return render(
        request,
        "workspace/partials/_basemap_picker.html",
        {
            "basemaps": basemaps,
            "workspace_pk": workspace_pk,
            "selected_basemap_id": selected_id,
        },
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def basemap_select(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Manage basemap selection for a workspace.

    GET: return current basemap config (style, type, attribution) as JSON.
    POST with basemap_id: save selection to session, return re-rendered picker.
    """
    if request.method == "GET":
        return _get_basemap_config(request, workspace_pk)
    return _post_basemap_select(request, workspace_pk)


def _get_basemap_config(request: HttpRequest, workspace_pk: int) -> JsonResponse:
    """Return the current basemap config for a workspace as JSON."""
    selected_id = _get_selected_basemap_id(request, workspace_pk)
    if selected_id is not None:
        basemap = get_object_or_404(Basemap, pk=selected_id)
    else:
        basemap = get_object_or_404(Basemap, is_default=True)

    return JsonResponse(
        {
            "id": basemap.pk,
            "name": basemap.name,
            "basemap_type": basemap.basemap_type,
            "style": basemap.resolve_style(),
            "attribution": basemap.attribution,
        }
    )


def _post_basemap_select(
    request: HttpRequest, workspace_pk: int
) -> HttpResponse:
    """Save basemap selection and return re-rendered picker partial."""
    raw_id = request.POST.get("basemap_id")
    basemaps = Basemap.objects.all().order_by("sort_order")

    if not raw_id:
        return render(
            request,
            "workspace/partials/_basemap_picker.html",
            {
                "basemaps": basemaps,
                "workspace_pk": workspace_pk,
                "selected_basemap_id": None,
            },
        )

    basemap = get_object_or_404(Basemap, pk=raw_id)
    _set_selected_basemap_id(request, workspace_pk, basemap.pk)
    logger.info(
        "Basemap '%s' (pk=%d) selected for workspace %d",
        basemap.name,
        basemap.pk,
        workspace_pk,
    )

    return render(
        request,
        "workspace/partials/_basemap_picker.html",
        {
            "basemaps": basemaps,
            "workspace_pk": workspace_pk,
            "selected_basemap_id": basemap.pk,
        },
    )
