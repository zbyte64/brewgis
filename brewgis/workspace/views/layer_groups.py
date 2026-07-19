"""Layer group management views for BrewGIS — htmx-driven CRUD."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Max
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace

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
    """Move a layer to a different group, reorder layers, or remove from group.

    POST params:
      - group_id: move layer into this group (existing behavior)
      - target_layer_pk: swap display_order with another layer (reorder)
    """
    layer = get_object_or_404(Layer, pk=layer_pk)
    target_pk = request.POST.get("target_layer_pk", "")
    group_id = request.POST.get("group_id", "")

    if target_pk:
        # Reorder: swap display_order with target layer
        target = get_object_or_404(Layer, pk=target_pk)
        layer.display_order, target.display_order = (
            target.display_order,
            layer.display_order,
        )
        layer.save()
        target.save()

        # Build swatch colors for the layer list panel
        workspace = layer.workspace
        swatch_colors: dict[int, str] = {}
        for lyr in workspace.layers.all():
            with suppress(SymbologyConfig.DoesNotExist):
                cfg = lyr.symbology
                swatch_colors[lyr.pk] = cfg.default_color or "#e0e0e0"
                continue
            swatch_colors[lyr.pk] = "#e0e0e0"

        context: dict[str, Any] = {
            "workspace": workspace,
            "scenario": None,
            "is_public_view": False,
            "layer_configs": {},
            "swatch_colors": swatch_colors,
        }
        return render(request, "workspace/partials/_layer_list_panel.html", context)

    if group_id:
        group = get_object_or_404(LayerGroup, pk=group_id, workspace=layer.workspace)
        layer.group = group
    else:
        layer.group = None
    layer.save()
    context = _list_context(layer.workspace)
    return render(request, "workspace/partials/_layer_group_list.html", context)
