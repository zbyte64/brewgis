"""Select a workspace's base canvas source table.

A workspace's base canvas is the parcel/feature table that scenarios paint
over (``Workspace.base_table``, defaulting to the shared ``public.base_canvas``
table). This lets a workspace instead point at any loaded Postgres table that
already has every required base-canvas column — a SQLMesh model's view, an
imported shapefile, the ETL pipeline's ``public.base_canvas`` — skipping the
manual ETL pipeline entirely (see
``services.sqlmesh_tables.list_base_canvas_candidates``).

The form also carries the workspace's built-form fill toggle
(``Workspace.fill_built_form``). With it on, the selected source is left exactly
as it is and a *new* table is materialized for the workspace to read instead
(``models/base_canvas/built_form_fill.py``): the closest-matching Building Type
replaces a ``built_form_key`` that names no Building Type of the workspace (the
pipeline's ``mixed_use`` placeholder, a blank, a NULL) and fills the NULL
built-form columns, while a key the source asserted is kept. The workspace's
effective base layer — what the map, the canvas views and the analysis models
read — is resolved in one place, ``Workspace.effective_base_table``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import Workspace
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates
from brewgis.workspace.services.workspace_base import adopt_base_table
from brewgis.workspace.views.built_forms import HtmxResponseMixin

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse
    from django.http import HttpResponseBase


def _base_canvas_choices() -> list[tuple[str | None, list[tuple[str, str]]]]:
    """Group the candidates into SQLMesh models and plain tables.

    Both are adoptable; they differ in where they come from — a model's view is
    something the project builds, a plain table is something the user loaded —
    and the plan treats them differently for exactly that reason (a model is
    snapshot-resolved, a plain table read as an external table). Naming the
    group is what lets a workspace find the table it just imported.
    """
    models: list[tuple[str, str]] = []
    tables: list[tuple[str, str]] = []
    for candidate in list_base_canvas_candidates():
        target = models if candidate.is_sqlmesh_model else tables
        target.append((candidate.qualified, candidate.qualified))
    # An empty optgroup renders as a bare label with nothing under it.
    return [
        (label, options)
        for label, options in (("SQLMesh models", models), ("Imported tables", tables))
        if options
    ]


class SelectBaseCanvasForm(forms.Form):
    base_table = forms.ChoiceField(
        label="Base canvas table",
        choices=_base_canvas_choices,
        help_text=(
            "Any loaded table carrying every required base canvas column, at the "
            "types the canvas views need, is listed — a SQLMesh model's view or a "
            "table you imported. A plain table is read as-is; scenarios paint over "
            "a copy-on-write view of it."
        ),
    )
    fill_built_form = forms.BooleanField(
        required=False,
        label="Fill built form by closest matching",
        help_text=(
            "Assign each parcel the closest-matching Building Type where its "
            "built_form_key names none of this workspace's Building Types — the "
            "pipeline's mixed_use placeholder, a blank and a NULL. A key that "
            "already names a Building Type is kept; du, pop, hh and emp are filled "
            "where they are NULL. Materializes a new table; the selected source is "
            "not modified."
        ),
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

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        self.workspace = get_object_or_404(Workspace, pk=kwargs["workspace_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial["base_table"] = self.workspace.base_table
        initial["fill_built_form"] = self.workspace.fill_built_form
        return initial

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=[self.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        adopt_base_table(
            self.workspace,
            base_table=form.cleaned_data["base_table"],
            fill_built_form=form.cleaned_data["fill_built_form"],
        )
        return super().form_valid(form)
