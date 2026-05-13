"""Views for launching and monitoring analysis pipeline runs."""

from __future__ import annotations

import json
from typing import Any
from typing import cast


from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites

_CONSTRAINTS_INITIAL = json.dumps(
    [
        {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"},
        {"table": "wetlands", "discount_pct": 100, "geom_col": "geom"},
        {"table": "steep_slopes", "discount_pct": 75, "geom_col": "geom"},
    ],
    indent=2,
)


def _discover_geom_tables(schema: str) -> list[tuple[str, str]]:
    """Discover tables in *schema* that have a geometry column.

    Returns a list of ``(table_name, label)`` tuples suitable for
    a ``Select`` widget's ``choices``.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT c.table_name
            FROM information_schema.columns c
            WHERE c.table_schema = %s
              AND c.udt_name IN ('geometry', 'geography')
              AND c.table_name NOT LIKE 'stage_%%'
            ORDER BY c.table_name
            """,
            [schema],
        )
        return [(row[0], row[0]) for row in cursor.fetchall()]


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
    scenario = forms.ModelChoiceField(
        queryset=Scenario.objects.all(),
        required=True,
        label="Scenario",
        help_text="Select a scenario for this analysis run.",
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

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize form, optionally auto-discovering parcel tables."""
        self._workspace: Workspace | None = cast(Workspace | None, kwargs.pop("workspace", None))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        if self._workspace:
            schema = self._workspace.db_schema
            choices = _discover_geom_tables(schema)
            if choices:
                self.fields["parcel_table"].widget = forms.widgets.Select(
                    choices=[("", "--- Select a table ---")] + choices,
                )
                self.fields[
                    "parcel_table"
                ].help_text = (
                    "Select a table from the workspace schema or type a custom name."
                )
                # Default base_canvas_table to the first detected staging stub
                default_stub = f"stage_{choices[0][0]}_base_canvas"
                self.fields["base_canvas_table"].initial = default_stub
                self.fields[
                    "base_canvas_table"
                ].help_text = "Auto-detected staging stub. Change to a real base canvas if available."

            # Filter scenario queryset to the selected workspace
            self.fields["scenario"].queryset = Scenario.objects.filter(  # type: ignore[attr-defined]
                workspace=self._workspace,
            )

    # Constraint layers (repeating group — simplified with JSON field)
    constraints_json = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 6, "class": "form-control font-monospace"}
        ),
        required=False,
        label="Constraints Configuration (JSON)",
        help_text=(
            "JSON array of constraint layer definitions. "
            'Example: [{"table": "floodplains", "discount_pct": 100}]'
        ),
        initial=_CONSTRAINTS_INITIAL,
    )
    column_mapping = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 4, "class": "form-control font-monospace"}
        ),
        required=False,
        label="Column Mapping (JSON)",
        help_text=(
            "Optional JSON mapping of canonical column names to actual table "
            'column names. Example: {"pop": "population", "hh": "households"}'
        ),
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

    def clean_column_mapping(self) -> dict[str, str] | None:
        """Parse and validate the column mapping JSON field."""
        data = self.cleaned_data.get("column_mapping")
        if not data:
            return None
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f"Invalid JSON: {e}") from e
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Column mapping must be a JSON object.")
        for key, value in parsed.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise forms.ValidationError(
                    "All keys and values in column mapping must be strings."
                )
        return parsed

    def clean(self) -> dict[str, Any] | None:
        """Validate analysis prerequisites before launching."""
        data = super().clean()
        if self.errors:
            return data
        if data is None:
            return None

        workspace: Workspace | None = data.get("workspace")
        parcel_table = data.get("parcel_table", "")
        if workspace and parcel_table:
            schema = workspace.db_schema
            built_form_table = data.get("built_form_table") or "built_forms"
            base_canvas_table = data.get("base_canvas_table")
            # Default to staging stub if no real base canvas specified
            if not base_canvas_table or base_canvas_table == "base_canvas":
                base_canvas_table = f"stage_{parcel_table}_base_canvas"
                data["base_canvas_table"] = base_canvas_table
            errors = check_analysis_prerequisites(
                schema=schema,
                parcel_table=parcel_table,
                built_form_table=built_form_table,
                base_canvas_table=base_canvas_table,
            )
            if errors:
                first = errors[0]
                self.add_error(first.field, first.message)

        return data


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class AnalysisLaunchView(FormView):
    """View to launch an analysis pipeline run."""

    form_class = AnalysisLaunchForm
    template_name = "form.html"

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        workspace_pk = self.request.GET.get("workspace")
        if workspace_pk:
            try:
                kwargs["workspace"] = Workspace.objects.get(pk=workspace_pk)
            except Workspace.DoesNotExist:
                pass
        return kwargs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Run Analysis"
        return context

    def form_valid(self, form: AnalysisLaunchForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        modules: list[str] = data["modules"]
        scenario: Scenario = data["scenario"]

        # Build dbt vars dict
        vars_: dict = {
            "source_schema": data.get("source_schema", "public"),
            "parcel_table": data["parcel_table"],
            "built_form_table": data.get("built_form_table", "built_forms"),
            "base_canvas_table": data.get("base_canvas_table", "base_canvas"),
            "target_schema": workspace.db_schema,
            "scenario_id": scenario.slug,
        }

        constraints = data.get("constraints_json")
        if constraints:
            vars_["constraints"] = constraints
        column_mapping = data.get("column_mapping")
        if column_mapping:
            vars_["column_mapping"] = column_mapping

        # Launch the pipeline
        run = run_analysis_pipeline(
            workspace_id=workspace.pk,
            module_names=modules,
            vars_=vars_,
            scenario_id=scenario.pk,
        )

        if self.request.htmx:  # type: ignore[attr-defined]
            html = render_to_string(
                "workspace/analysis/status.html#analysis-status",
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

    vmt_fee_data = None
    if run.status == "completed" and "vmt_fee" in (run.modules or []):
        vmt_fee_table = f"vmt_fee_{run.scenario.slug}"
        schema = run.workspace.db_schema
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COALESCE(SUM(fee_revenue_total), 0), "
                    f"COALESCE(SUM(revenue_forgone), 0), "
                    f"COALESCE(SUM(vmt_exempt), 0) "
                    f'FROM "{schema}"."{vmt_fee_table}"'
                )
                row = cursor.fetchone()
                if row:
                    vmt_fee_data = {
                        "revenue": round(row[0], 2),
                        "revenue_forgone": round(row[1], 2),
                        "vmt_exempt": round(row[2], 2),
                    }
        except Exception:
            pass

    return render(
        request,
        "workspace/analysis/status.html#analysis-status",
        {"run": run, "vmt_fee_data": vmt_fee_data},
    )


@user_passes_test(lambda u: u.is_authenticated)
def analysis_list(request: HttpRequest) -> HttpResponse:
    """List recent analysis runs for the current user's workspaces."""
    runs = AnalysisRun.objects.select_related("workspace").order_by("-created_at")[:50]
    return render(
        request,
        "workspace/analysis/list.html",
        {"runs": runs},
    )


@require_POST
def check_prerequisites(request: HttpRequest) -> HttpResponse:
    """htmx endpoint: run preflight validation and render results inline."""
    schema = request.POST.get("source_schema", "public")
    parcel_table = request.POST.get("parcel_table", "")
    built_form_table = request.POST.get("built_form_table", "built_forms")
    base_canvas_table = request.POST.get("base_canvas_table", "")

    if not parcel_table:
        html = "<div class='alert alert-warning'>No parcel table specified.</div>"
        return HttpResponse(html)

    # Default base_canvas_table to staging stub if empty
    if not base_canvas_table or base_canvas_table == "base_canvas":
        base_canvas_table = f"stage_{parcel_table}_base_canvas"

    errors = check_analysis_prerequisites(
        schema=schema,
        parcel_table=parcel_table,
        built_form_table=built_form_table,
        base_canvas_table=base_canvas_table,
    )

    if not errors:
        html = "<div class='alert alert-success'>All prerequisites met.&#8203;</div>"
    else:
        items = "".join(f"<li>{e.message}</li>" for e in errors)
        html = (
            f"<div class='alert alert-danger'>"
            f"<strong>Prerequisites check failed:</strong>"
            f"<ul>{items}</ul></div>"
        )

    return HttpResponse(html)
