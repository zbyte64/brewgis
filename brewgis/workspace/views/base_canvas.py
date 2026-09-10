"""Select a workspace's base canvas source table.

A workspace's base canvas is the parcel/feature table that scenarios paint
over (``Workspace.base_table``, defaulting to the shared ``public.base_canvas``
table). This lets a workspace instead point at a SQLMesh-generated table that
already has every required base-canvas column (see
``services.sqlmesh_tables.list_base_canvas_candidates``), skipping the manual
ETL pipeline entirely.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING
from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import refresh_canvas_view
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates
from brewgis.workspace.views.built_forms import HtmxResponseMixin

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


def _base_canvas_choices() -> list[tuple[str, str]]:
    return [(info.qualified, info.qualified) for info in list_base_canvas_candidates()]


class SelectBaseCanvasForm(forms.Form):
    base_table = forms.ChoiceField(
        label="Base canvas table",
        choices=_base_canvas_choices,
        help_text="Only SQLMesh tables with every required base canvas column are listed.",
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class SelectBaseCanvasView(HtmxResponseMixin, FormView):
    form_class = SelectBaseCanvasForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    extra_context = {"title": "Select Base Canvas"}

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.workspace = get_object_or_404(Workspace, pk=kwargs["workspace_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial["base_table"] = self.workspace.base_table
        return initial

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=[self.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        self.workspace.base_table = form.cleaned_data["base_table"]
        self.workspace.save(update_fields=["base_table"])
        schema, table = self.workspace.base_table.split(".", 1)
        register_result_layer(
            self.workspace.pk,
            schema,
            table,
            key=BASE_CANVAS_LAYER_KEY,
            name="Base Canvas",
            description=f"Workspace base canvas ({self.workspace.base_table})",
        )
        for scenario in self.workspace.scenarios.all():
            with contextlib.suppress(Exception):
                refresh_canvas_view(scenario, self.workspace.base_table)
        logger.info(
            "Workspace %s base_table set to %s",
            self.workspace.pk,
            self.workspace.base_table,
        )
        return super().form_valid(form)
