"""View for spatial allocation between layers."""

from __future__ import annotations

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.tasks import run_spatial_allocation


class AllocateForm(forms.Form):
    """Form to configure a spatial allocation operation."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.label_class = "form-label"
        self.helper.field_class = "mb-3"

    workspace = forms.ModelChoiceField(
        queryset=Workspace.objects.all(),
        label="Workspace",
    )
    source_table = forms.CharField(
        max_length=128,
        label="Source Table",
        help_text="Table containing source data (e.g., census block groups).",
    )
    source_geom_col = forms.CharField(
        max_length=64,
        initial="geom",
        label="Source Geometry Column",
    )
    target_table = forms.CharField(
        max_length=128,
        label="Target Table",
        help_text="Table to allocate data to (e.g., parcels).",
    )
    target_geom_col = forms.CharField(
        max_length=64,
        initial="geom",
        label="Target Geometry Column",
    )
    columns = forms.CharField(
        max_length=512,
        label="Columns to Allocate",
        help_text="Comma-separated list of column names to allocate.",
    )
    column_prefix = forms.CharField(
        max_length=64,
        required=False,
        label="Column Prefix",
        help_text="Optional prefix for new columns on target (e.g., 'acs_').",
    )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class AllocateView(FormView):
    """View to run spatial allocation."""

    form_class = AllocateForm
    template_name = "form.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Spatial Allocation"
        return context

    def form_valid(self, form: AllocateForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        columns = [c.strip() for c in data["columns"].split(",") if c.strip()]

        run = DataImportRun.objects.create(
            workspace=workspace,
            import_type="allocate",
            params={
                "source_table": data["source_table"],
                "target_table": data["target_table"],
                "columns": columns,
                "column_prefix": data.get("column_prefix", ""),
            },
            status="pending",
        )

        run_spatial_allocation.delay(
            run_pk=run.pk,
            source_schema=workspace.db_schema,
            source_table=data["source_table"],
            target_schema=workspace.db_schema,
            target_table=data["target_table"],
            columns=columns,
            column_prefix=data.get("column_prefix", ""),
            source_geom_col=data["source_geom_col"],
            target_geom_col=data["target_geom_col"],
        )

        if self.request.htmx:  # type: ignore[attr-defined]
            html = render_to_string(
                "workspace/import/status.html#import-status",
                {"run": run},
                request=self.request,
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = "import-started"
            return response

        return render(
            self.request,
            "workspace/import/status.html",
            {"run": run},
        )
