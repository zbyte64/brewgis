"""Views for launching and monitoring analysis pipeline runs."""
from __future__ import annotations

import json

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Workspace

_CONSTRAINTS_INITIAL = json.dumps([
    {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"},
    {"table": "wetlands", "discount_pct": 100, "geom_col": "geom"},
    {"table": "steep_slopes", "discount_pct": 75, "geom_col": "geom"},
], indent=2)


class AnalysisLaunchForm(forms.Form):
    """Form to configure and launch an analysis pipeline run."""

    workspace = forms.ModelChoiceField(
        queryset=Workspace.objects.all(),
        label="Workspace",
    )
    modules = forms.MultipleChoiceField(
        choices=[
            ("env_constraint", "Environmental Constraint"),
            ("core", "Scenario Builder (Core)"),
        ],
        widget=forms.CheckboxSelectMultiple,
        label="Analysis Modules",
        help_text="Select the modules to run. Dependencies are resolved automatically.",
    )
    scenario_id = forms.CharField(
        max_length=64,
        required=False,
        label="Scenario ID",
        help_text="Optional unique identifier for this run. Auto-generated if blank.",
    )
    parcel_table = forms.CharField(
        max_length=128,
        label="Parcel Table",
        help_text="Table name containing parcels with built form assignments.",
    )
    built_form_table = forms.CharField(
        max_length=128,
        required=False,
        label="Built Form Table",
        help_text="Table name with BuildingType definitions. Defaults to 'built_forms'.",
        initial="built_forms",
    )
    source_schema = forms.CharField(
        max_length=64,
        required=False,
        label="Source Schema",
        help_text="Database schema containing source tables.",
        initial="public",
    )
    base_canvas_table = forms.CharField(
        max_length=128,
        required=False,
        label="Base Canvas Table",
        help_text="Existing condition table for increment computation.",
        initial="base_canvas",
    )

    # Constraint layers (repeating group — simplified with JSON field)
    constraints_json = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6, "class": "form-control font-monospace"}),
        required=False,
        label="Constraints Configuration (JSON)",
        help_text=(
            'JSON array of constraint layer definitions. '
            'Example: [{"table": "floodplains", "discount_pct": 100}]'
        ),
        initial=_CONSTRAINTS_INITIAL,
    )

    def clean_constraints_json(self) -> list[dict] | None:
        """Parse and validate the constraints JSON field."""
        data = self.cleaned_data.get("constraints_json")
        if not data:
            return None

        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            msg = f"Invalid JSON: {e}"
            raise forms.ValidationError(msg) from e

        if not isinstance(parsed, list):
            msg = "Constraints must be a JSON array."
            raise forms.ValidationError(msg)

        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                msg = f"Item {i} must be an object."
                raise forms.ValidationError(msg)
            if "table" not in item:
                msg = f"Item {i} missing required 'table' key."
                raise forms.ValidationError(msg)
            if "discount_pct" not in item:
                msg = f"Item {i} missing required 'discount_pct' key."
                raise forms.ValidationError(msg)

        return parsed


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class AnalysisLaunchView(FormView):
    """View to launch an analysis pipeline run."""

    form_class = AnalysisLaunchForm
    template_name = "form.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Run Analysis"
        return context

    def form_valid(self, form: AnalysisLaunchForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        modules: list[str] = data["modules"]
        scenario_id = data.get("scenario_id") or None

        # Build dbt vars dict
        vars_: dict = {
            "source_schema": data.get("source_schema", "public"),
            "parcel_table": data["parcel_table"],
            "built_form_table": data.get("built_form_table", "built_forms"),
            "base_canvas_table": data.get("base_canvas_table", "base_canvas"),
            "target_schema": workspace.db_schema,
        }

        if scenario_id:
            vars_["scenario_id"] = scenario_id

        constraints = data.get("constraints_json")
        if constraints:
            vars_["constraints"] = constraints

        # Launch the pipeline
        run = run_analysis_pipeline(
            workspace_id=workspace.pk,
            module_names=modules,
            vars_=vars_,
        )

        if self.request.htmx:  # type: ignore[attr-defined]
            html = render_to_string(
                "workspace/analysis/partials/_status.html",
                {"run": run},
                request=self.request,
            )
            response = HttpResponse(html)
            # Trigger polling
            response["HX-Trigger"] = "analysis-started"
            return response

        return render(
            self.request,
            "workspace/analysis/status.html",
            {"run": run},
        )


def analysis_status(request: HttpRequest, run_pk: int) -> HttpResponse:
    """htmx-polled status partial for an analysis run."""
    run = get_object_or_404(AnalysisRun, pk=run_pk)
    return render(
        request,
        "workspace/analysis/partials/_status.html",
        {"run": run},
    )


def analysis_list(request: HttpRequest) -> HttpResponse:
    """List recent analysis runs for the current user's workspaces."""
    runs = AnalysisRun.objects.select_related("workspace").order_by("-created_at")[:50]
    return render(
        request,
        "workspace/analysis/list.html",
        {"runs": runs},
    )
