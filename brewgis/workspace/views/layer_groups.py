"""Layer group management views for BrewGIS — htmx-driven CRUD."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Max
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from brewgis.workspace.models import Layer, LayerGroup, Workspace

logger = logging.getLogger(__name__)


def _list_context(workspace: Workspace) -> dict[str, Any]:
    """Build shared context for the layer group list partial."""
    groups = (
        LayerGroup.objects.filter(workspace=workspace)
        .prefetch_related("layers")
        .order_by("display_order")
    )
    ungrouped = Layer.objects.filter(workspace=workspace, group__isnull=True).order_by(
        "display_order"
    )
    return {
        "workspace": workspace,
        "groups": groups,
        "ungrouped": ungrouped,
    }


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_group_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return a partial listing all layer groups with their layers for a workspace."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context = _list_context(workspace)
    return render(request, "workspace/partials/_layer_group_list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_group_create(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Create a new layer group (GET=form, POST=create)."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/partials/_layer_group_form.html",
                {"workspace": workspace, "error": "Group name is required."},
            )
        max_order = LayerGroup.objects.filter(workspace=workspace).aggregate(
            max_order=Max("display_order")
        )
        next_order = (max_order.get("max_order") or 0) + 1
        LayerGroup.objects.create(
            workspace=workspace, name=name, display_order=next_order
        )
        context = _list_context(workspace)
        return render(request, "workspace/partials/_layer_group_list.html", context)
    return render(
        request,
        "workspace/partials/_layer_group_form.html",
        {"workspace": workspace},
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_group_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Rename a layer group (GET=form, POST=update)."""
    group = get_object_or_404(LayerGroup, pk=pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/partials/_layer_group_form.html",
                {"group": group, "error": "Group name is required."},
            )
        group.name = name
        group.save()
        context = _list_context(group.workspace)
        return render(request, "workspace/partials/_layer_group_list.html", context)
    return render(
        request,
        "workspace/partials/_layer_group_form.html",
        {"group": group},
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def layer_group_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a layer group (layers become ungrouped via SET_NULL)."""
    group = get_object_or_404(LayerGroup, pk=pk)
    workspace = group.workspace
    group.delete()
    context = _list_context(workspace)
    return render(request, "workspace/partials/_layer_group_list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def layer_group_move_layer(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Move a layer to a different group, or remove from group."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    group_id = request.POST.get("group_id", "")
    if group_id:
        group = get_object_or_404(LayerGroup, pk=group_id, workspace=layer.workspace)
        layer.group = group
    else:
        layer.group = None
    layer.save()
    context = _list_context(layer.workspace)
    return render(request, "workspace/partials/_layer_group_list.html", context)
