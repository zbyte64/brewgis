from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic.edit import CreateView

from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.views.built_forms import HtmxResponseMixin


class CreateLayerForm(forms.ModelForm):
    class Meta:
        model = Layer
        fields = ["workspace", "key", "name", "db_table", "layer_source", "description"]


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class CreateLayerView(HtmxResponseMixin, CreateView):
    form_class = CreateLayerForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"

    def get_redirect_url(self) -> str:
        assert self.object is not None
        return reverse(self.success_url_name, args=[self.object.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        self.object = form.save()
        with suppress(Exception):
            auto_generate_symbology(self.object)
        return super().form_valid(form)


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a layer and return updated layer list from htmx.

    Related SymbologyConfig and StyleClass records cascade on delete.
    LayerGroup FK uses SET_NULL, so group membership is cleared (not removed).
    """
    layer = get_object_or_404(Layer, pk=pk)
    workspace = layer.workspace

    # Prevent deletion of canvas layers
    if layer.db_table and layer.db_table.startswith("base_canvas_"):
        return HttpResponse("Cannot delete canvas layers", status=400)

    workspace_pk = workspace.pk
    layer.delete()

    if request.headers.get("HX-Request") == "true":
        # Build swatch colors for the legend list
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
        response = render(
            request,
            "workspace/partials/_layer_list_panel.html",
            context,
        )
        response["HX-Trigger"] = json.dumps(
            {
                "layer-deleted": {"layerPk": pk},
            }
        )
        return response

    redirect_url = reverse("workspace:workspace_detail", kwargs={"pk": workspace_pk})
    return HttpResponseRedirect(redirect_url)
