"""Views for managing external map services (WMS/WMTS/WFS/XYZ) via htmx."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from brewgis.workspace.models import ExternalMapService, Workspace


def _list_context(workspace: Workspace) -> dict[str, Any]:
    """Build shared context for the external service list partial."""
    return {
        "workspace": workspace,
        "services": ExternalMapService.objects.filter(
            workspace=workspace, is_active=True
        ).order_by("display_order"),
    }


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def external_service_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Return HTML partial listing active external services for a workspace."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    context = _list_context(workspace)
    return render(request, "workspace/partials/_external_service_list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def external_service_add(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Create a new external map service (GET=form, POST=create)."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        service_type = request.POST.get("service_type", "").strip()
        url = request.POST.get("url", "").strip()
        layers_param = request.POST.get("layers_param", "").strip()
        attribution = request.POST.get("attribution", "").strip()

        errors: dict[str, str] = {}
        if not name:
            errors["name"] = "Service name is required."
        if not service_type:
            errors["service_type"] = "Service type is required."
        elif service_type not in dict(ExternalMapService.ServiceType.choices):
            errors["service_type"] = f"Invalid service type: {service_type}"
        if not url:
            errors["url"] = "URL is required."

        if errors:
            return render(
                request,
                "workspace/partials/_external_service_form.html",
                {
                    "workspace": workspace,
                    "errors": errors,
                    "service_types": ExternalMapService.ServiceType.choices,
                    "values": {
                        "name": name,
                        "service_type": service_type,
                        "url": url,
                        "layers_param": layers_param,
                        "attribution": attribution,
                    },
                },
            )

        ExternalMapService.objects.create(
            workspace=workspace,
            name=name,
            service_type=service_type,
            url=url,
            layers_param=layers_param,
            attribution=attribution,
        )

        # Return the updated list partial
        context = _list_context(workspace)
        response = render(
            request, "workspace/partials/_external_service_list.html", context
        )
        response["HX-Redirect"] = ""
        return response

    # GET — return empty form
    return render(
        request,
        "workspace/partials/_external_service_form.html",
        {
            "workspace": workspace,
            "errors": {},
            "service_types": ExternalMapService.ServiceType.choices,
            "values": {},
        },
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def external_service_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Toggle the active state of an external service."""
    service = get_object_or_404(ExternalMapService, pk=pk)
    service.is_active = not service.is_active
    service.save()
    context = _list_context(service.workspace)
    return render(request, "workspace/partials/_external_service_list.html", context)


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def external_service_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete an external service and return the updated list partial."""
    service = get_object_or_404(ExternalMapService, pk=pk)
    workspace = service.workspace
    service.delete()
    context = _list_context(workspace)
    return render(request, "workspace/partials/_external_service_list.html", context)
