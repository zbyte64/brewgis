from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from crispy_forms.helper import FormHelper
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
from django.views.generic.edit import FormView

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.sqlmesh_tables import list_sqlmesh_tables
from brewgis.workspace.symbology.auto import auto_generate_symbology
from brewgis.workspace.views.built_forms import HtmxResponseMixin


class CreateLayerForm(forms.ModelForm):
    class Meta:
        model = Layer
        fields = ["workspace", "key", "name", "db_table", "layer_source", "description"]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False
        workspace_pk = self.initial.get("workspace")
        if workspace_pk:
            self.fields["workspace"].queryset = Workspace.objects.filter(
                pk=workspace_pk,
            )
            self.fields["workspace"].widget = forms.HiddenInput()


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class CreateLayerView(HtmxResponseMixin, CreateView):
    form_class = CreateLayerForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        workspace_pk = self.request.GET.get("workspace")
        if workspace_pk:
            initial["workspace"] = workspace_pk
        return initial

    def get_redirect_url(self) -> str:
        assert self.object is not None
        return reverse(self.success_url_name, args=[self.object.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        self.object = form.save()
        with suppress(Exception):
            auto_generate_symbology(self.object)
        return super().form_valid(form)


def _sqlmesh_table_choices() -> list[tuple[str, list[tuple[str, str]]]]:
    """Group importable sqlmesh tables into optgroups keyed by schema."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for info in list_sqlmesh_tables():
        label = f"{info.table} ({info.geometry_type or 'no geometry'})"
        grouped.setdefault(info.schema, []).append((info.qualified, label))
    return list(grouped.items())


class ImportSqlmeshLayerForm(forms.Form):
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    sqlmesh_table = forms.ChoiceField(
        label="SQLMesh table",
        choices=_sqlmesh_table_choices,
    )
    name = forms.CharField(required=False, max_length=255)
    description = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False
        workspace_pk = self.initial.get("workspace")
        if workspace_pk:
            self.fields["workspace"].queryset = Workspace.objects.filter(
                pk=workspace_pk,
            )
            self.fields["workspace"].widget = forms.HiddenInput()


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class ImportSqlmeshLayerView(HtmxResponseMixin, FormView):
    form_class = ImportSqlmeshLayerForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    extra_context = {"title": "Import SQLMesh Table as Layer"}

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        workspace_pk = self.request.GET.get("workspace")
        if workspace_pk:
            initial["workspace"] = workspace_pk
        return initial

    def get_redirect_url(self) -> str:
        assert self.object is not None
        return reverse(self.success_url_name, args=[self.object.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        workspace = form.cleaned_data["workspace"]
        schema, table = form.cleaned_data["sqlmesh_table"].split(".", 1)
        self.object = register_result_layer(
            workspace.pk,
            schema,
            table,
            name=form.cleaned_data["name"] or None,
            description=form.cleaned_data["description"] or None,
        )
        if self.object is None:
            form.add_error(None, "Could not import this table as a layer.")
            return self.form_invalid(form)
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
    if layer.key == BASE_CANVAS_LAYER_KEY or (
        layer.db_table and layer.db_table.startswith("base_canvas_")
    ):
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
