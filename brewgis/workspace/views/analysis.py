"""Views for launching and monitoring analysis pipeline runs."""

from __future__ import annotations

import json
from typing import Any
from typing import cast

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.http import Http404
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from brewgis.workspace.analysis.data_export import ensure_export_exists_isolated
from brewgis.workspace.analysis.module_registry import CANONICAL_COLUMN_NAMES
from brewgis.workspace.analysis.module_registry import MODULE_LABELS
from brewgis.workspace.analysis.module_registry import get_available_analyses
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import launch_analysis_run
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.views.built_forms import HtmxResponseMixin

_CONSTRAINTS_INITIAL = json.dumps(
    [
        {"table": "floodplains", "discount_pct": 100, "geom_col": "geom"},
        {"table": "wetlands", "discount_pct": 100, "geom_col": "geom"},
        {"table": "steep_slopes", "discount_pct": 75, "geom_col": "geom"},
    ],
    indent=2,
)


class AnalysisLaunchForm(forms.Form):
    """Form to configure and launch an analysis pipeline run."""

    workspace = forms.ModelChoiceField(
        queryset=Workspace.objects.all(),
        label="Workspace",
    )
    modules = forms.MultipleChoiceField(
        choices=list(MODULE_LABELS.items()),
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
        widget=forms.HiddenInput(),
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
        """Initialize form, defaulting tables to the workspace's configuration."""
        self._workspace: Workspace | None = cast(
            "Workspace | None", kwargs.pop("workspace", None)
        )
        scenario: Scenario | None = cast(
            "Scenario | None", kwargs.pop("scenario", None)
        )
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        self.helper = FormHelper()
        self.helper.form_tag = False

        if self._workspace:
            self.fields["workspace"].queryset = Workspace.objects.filter(
                pk=self._workspace.pk,
            )
            self.fields["workspace"].initial = self._workspace.pk
            self.fields["workspace"].widget = forms.HiddenInput()

            # The workspace's configured base canvas already has one row per
            # parcel, so it doubles as the parcel table unless overridden.
            self.fields["base_canvas_table"].initial = self._workspace.base_table

            if scenario is not None:
                # Default to the scenario's canvas view — it COALESCEs any
                # painted overlay over the base canvas, so an analysis run
                # picks up paint edits by default instead of silently
                # ignoring them. Harmless for an unpainted scenario since
                # the view then falls through to base canvas values anyway.
                self.fields[
                    "parcel_table"
                ].initial = f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"
                self.fields["parcel_table"].help_text = (
                    "Defaults to the selected scenario's canvas view "
                    "(base canvas + painted edits). Override to use a "
                    "different parcel source."
                )
                self.fields["scenario"].initial = scenario.pk
            else:
                self.fields["parcel_table"].initial = self._workspace.base_table
                self.fields["parcel_table"].help_text = (
                    "Defaults to the workspace's base canvas table. "
                    "Override to use a different parcel source."
                )

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
            base_canvas_table = data.get("base_canvas_table") or workspace.base_table
            data["base_canvas_table"] = base_canvas_table

            # Mechanically re-sync already-configured BuildingType rows into
            # the workspace's built_forms table before checking for it. This
            # never invents data — a workspace with no BuildingType rows
            # configured still produces an empty table, which the prerequisite
            # check below still catches and reports.
            #
            # Uses its own DB connection (not Django's request-scoped one) so
            # the write commits immediately: under ATOMIC_REQUESTS the whole
            # view runs in one transaction, but SQLMesh's engine adapter opens
            # a separate connection to run the plan — it can't see this table
            # until it's actually committed, not just pending in our own txn.
            bt_schema, bt_table = (
                built_form_table.split(".", 1)
                if "." in built_form_table
                else (schema, built_form_table)
            )
            ensure_export_exists_isolated(workspace, schema=bt_schema, table=bt_table)

            errors = check_analysis_prerequisites(
                schema=schema,
                parcel_table=parcel_table,
                built_form_table=built_form_table,
                base_canvas_table=base_canvas_table,
            )
            if errors:
                first = errors[0]
                # A hidden field (e.g. built_form_table) renders without an
                # inline error slot, so its message would otherwise vanish
                # silently. Surface it as a non-field error instead so it's
                # always visible regardless of which field it's attached to.
                if self.fields[first.field].widget.is_hidden:
                    self.add_error(None, first.message)
                else:
                    self.add_error(first.field, first.message)

        return data


# Fixed constraint layers offered as individual discount-% fields on
# AnalysisModuleForm — mirrors _CONSTRAINTS_INITIAL above (the same three
# layers AnalysisLaunchForm's constraints_json field defaults to), just
# surfaced as plain number inputs instead of JSON so the map view's
# per-analysis form never requires typing JSON.
_CONSTRAINT_LAYERS: list[tuple[str, str, str, int]] = [
    # each entry is field_name, table, geom_col, default_pct
    ("floodplain_discount_pct", "floodplains", "geom", 100),
    ("wetlands_discount_pct", "wetlands", "geom", 100),
    ("steep_slopes_discount_pct", "steep_slopes", "geom", 75),
]


class AnalysisModuleForm(forms.Form):
    """Parameter form for launching a single analysis from its map-view card.

    Unlike ``AnalysisLaunchForm`` (a generic multi-module launcher with raw
    JSON textareas for constraints/column mapping), this form is bound to one
    specific analysis module and exposes every relevant parameter as its own
    field — no JSON entry required.
    """

    scenario = forms.ModelChoiceField(
        queryset=Scenario.objects.all(),
        required=True,
        label="Scenario",
    )
    parcel_table = forms.CharField(
        max_length=128,
        label="Parcel Table",
        help_text="Table name containing parcels with built form assignments.",
    )
    built_form_table = forms.CharField(
        max_length=128,
        required=False,
        widget=forms.HiddenInput(),
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
        """Initialize the form for one ``module``, adding only its relevant fields."""
        self._workspace: Workspace | None = cast(
            "Workspace | None", kwargs.pop("workspace", None)
        )
        scenario: Scenario | None = cast(
            "Scenario | None", kwargs.pop("scenario", None)
        )
        module: str = cast("str", kwargs.pop("module"))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        deps = resolve_module_order([module])
        needs_constraints = "env_constraint" in deps
        needs_column_mapping = "core" in deps

        if needs_constraints:
            for field_name, _table, _geom_col, default_pct in _CONSTRAINT_LAYERS:
                self.fields[field_name] = forms.IntegerField(
                    required=False,
                    min_value=0,
                    max_value=100,
                    initial=default_pct,
                    label=f"{_table.replace('_', ' ').title()} discount %",
                    help_text="% of this layer's overlapping acreage excluded from developable land.",
                )

        if needs_column_mapping:
            for name in CANONICAL_COLUMN_NAMES:
                self.fields[f"column_{name}"] = forms.CharField(
                    required=False,
                    label=f"{name.replace('_', ' ').title()} column override",
                    help_text=f"Use if your source table names this column something other than '{name}'.",
                )

        self.helper = FormHelper()
        self.helper.form_tag = False

        if self._workspace:
            # The workspace's configured base canvas already has one row per
            # parcel, so it doubles as the parcel table unless overridden.
            self.fields["base_canvas_table"].initial = self._workspace.base_table

            if scenario is not None:
                # Default to the scenario's canvas view — it COALESCEs any
                # painted overlay over the base canvas, so an analysis run
                # picks up paint edits by default instead of silently
                # ignoring them.
                self.fields[
                    "parcel_table"
                ].initial = f"{scenario.target_schema}.scenario_{scenario.slug}_canvas"
                self.fields["parcel_table"].help_text = (
                    "Defaults to the selected scenario's canvas view "
                    "(base canvas + painted edits). Override to use a "
                    "different parcel source."
                )
                self.fields["scenario"].initial = scenario.pk
            else:
                self.fields["parcel_table"].initial = self._workspace.base_table

            self.fields["scenario"].queryset = Scenario.objects.filter(  # type: ignore[attr-defined]
                workspace=self._workspace,
            )

    def clean(self) -> dict[str, Any] | None:
        """Validate analysis prerequisites before launching (same checks as AnalysisLaunchForm)."""
        data = super().clean()
        if self.errors:
            return data
        if data is None:
            return None

        workspace: Workspace | None = self._workspace
        parcel_table = data.get("parcel_table", "")
        if workspace and parcel_table:
            schema = workspace.db_schema
            built_form_table = data.get("built_form_table") or "built_forms"
            base_canvas_table = data.get("base_canvas_table") or workspace.base_table
            data["base_canvas_table"] = base_canvas_table

            # See AnalysisLaunchForm.clean() for why this uses its own DB
            # connection rather than Django's request-scoped one.
            bt_schema, bt_table = (
                built_form_table.split(".", 1)
                if "." in built_form_table
                else (schema, built_form_table)
            )
            ensure_export_exists_isolated(workspace, schema=bt_schema, table=bt_table)

            errors = check_analysis_prerequisites(
                schema=schema,
                parcel_table=parcel_table,
                built_form_table=built_form_table,
                base_canvas_table=base_canvas_table,
            )
            if errors:
                first = errors[0]
                if self.fields[first.field].widget.is_hidden:
                    self.add_error(None, first.message)
                else:
                    self.add_error(first.field, first.message)

        return data

    def build_vars(self, workspace: Workspace) -> dict[str, Any]:
        """Assemble the SQLMesh vars dict for this run from individual fields."""
        data = self.cleaned_data
        scenario: Scenario = data["scenario"]
        vars_: dict[str, Any] = {
            "source_schema": data.get("source_schema") or "public",
            "parcel_table": data["parcel_table"],
            "built_form_table": data.get("built_form_table") or "built_forms",
            "base_canvas_table": data.get("base_canvas_table") or "base_canvas",
            "target_schema": workspace.db_schema,
            "scenario_id": scenario.slug,
        }

        constraints = []
        for field_name, table, geom_col, _default_pct in _CONSTRAINT_LAYERS:
            pct = data.get(field_name)
            if pct is not None:
                constraints.append(
                    {"table": table, "discount_pct": pct, "geom_col": geom_col}
                )
        if constraints:
            vars_["constraints"] = constraints

        column_mapping = {
            name: data[f"column_{name}"]
            for name in CANONICAL_COLUMN_NAMES
            if data.get(f"column_{name}")
        }
        if column_mapping:
            vars_["column_mapping"] = column_mapping

        return vars_


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class AnalysisLaunchView(HtmxResponseMixin, FormView):
    """View to launch an analysis pipeline run."""

    form_class = AnalysisLaunchForm
    template_name = "form.html"

    def get_form_kwargs(self) -> dict[str, object]:
        kwargs = super().get_form_kwargs()
        # The panel URL passes the workspace as a path segment
        # (``workspace_pk``); a bare ``?workspace=`` query param is also
        # accepted for direct links.
        workspace_pk = self.request.GET.get("workspace") or self.kwargs.get(
            "workspace_pk",
        )
        workspace: Workspace | None = None
        if workspace_pk:
            try:
                workspace = Workspace.objects.get(pk=workspace_pk)
                kwargs["workspace"] = workspace
            except Workspace.DoesNotExist:
                pass

        # ``?scenario=`` follows the same convention ``panel_layer_list``
        # uses to learn the map's currently-active scenario.
        scenario_pk = self.request.GET.get("scenario")
        if workspace is not None and scenario_pk:
            kwargs["scenario"] = Scenario.objects.filter(
                pk=scenario_pk, workspace=workspace
            ).first()
        return kwargs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Run Analysis"

        workspace_pk = self.request.GET.get("workspace") or self.kwargs.get(
            "workspace_pk",
        )
        if workspace_pk:
            try:
                workspace = Workspace.objects.get(pk=workspace_pk)
            except Workspace.DoesNotExist:
                workspace = None
            if workspace is not None:
                canvas_map = {
                    str(s.pk): f"{s.target_schema}.scenario_{s.slug}_canvas"
                    for s in workspace.scenarios.all()
                }
                canvas_map[""] = workspace.base_table
                context["scenario_canvas_map"] = json.dumps(canvas_map)
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
            module_labels = ", ".join(get_module_label(m) for m in modules)
            response["HX-Trigger"] = json.dumps(
                {
                    # Trigger polling
                    "analysis-started": True,
                    "show-toast": f"Analysis started: {module_labels}",
                },
            )
            return response

        return render(
            self.request,
            "workspace/analysis/status.html",
            {"run": run},
        )


def analysis_status(request: HttpRequest, run_pk: int) -> HttpResponse:
    """Analysis run detail — full page on a direct visit, htmx-polled partial otherwise."""
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

    template_name = (
        "workspace/analysis/status.html#analysis-status"
        if request.htmx  # type: ignore[attr-defined]
        else "workspace/analysis/status.html"
    )
    return render(
        request,
        template_name,
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


# ─────────────────────────────────────────────────────────────────────
#  Analysis panel (map view) — one card per available analysis
# ─────────────────────────────────────────────────────────────────────


def _get_active_scenario(request: HttpRequest, workspace: Workspace) -> Scenario | None:
    """Resolve the map's currently-active scenario from ``?scenario=``.

    Same convention as ``panel_layer_list`` — the map passes its active
    scenario as a query param so panel views default to its data.
    """
    scenario_pk = request.GET.get("scenario")
    if not scenario_pk:
        return None
    return Scenario.objects.filter(pk=scenario_pk, workspace=workspace).first()


def _get_analysis_meta(module_key: str) -> dict[str, Any]:
    """Look up one analysis's card metadata by module key, or 404."""
    meta = next(
        (a for a in get_available_analyses() if a["key"] == module_key),
        None,
    )
    if meta is None:
        msg = f"Unknown analysis module: {module_key}"
        raise Http404(msg)
    return meta


def _analysis_card_context(
    workspace: Workspace,
    scenario: Scenario | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Build the render context for one analysis's card.

    Shared by the card-list panel and the single-card polling endpoint so
    both always render identical markup.
    """
    runs = AnalysisRun.objects.filter(workspace=workspace)
    if scenario is not None:
        runs = runs.filter(scenario=scenario)
    last_run = (
        runs.filter(modules__contains=[meta["key"]]).order_by("-created_at").first()
    )
    return {
        "workspace": workspace,
        "scenario": scenario,
        "analysis": meta,
        "last_run": last_run,
    }


@user_passes_test(lambda u: u.is_authenticated)
def panel_analysis_card_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Left-sidebar Analysis panel — a card per available analysis module."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = _get_active_scenario(request, workspace)
    cards = [
        _analysis_card_context(workspace, scenario, meta)
        for meta in get_available_analyses()
    ]
    return render(
        request,
        "workspace/analysis/_analysis_panel.html",
        {"workspace": workspace, "scenario": scenario, "cards": cards},
    )


@user_passes_test(lambda u: u.is_authenticated)
def analysis_card_status(
    request: HttpRequest, workspace_pk: int, module_key: str
) -> HttpResponse:
    """Single-card htmx polling target — self-refreshes while its run is active."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = _get_active_scenario(request, workspace)
    meta = _get_analysis_meta(module_key)
    context = _analysis_card_context(workspace, scenario, meta)
    return render(request, "workspace/analysis/_analysis_card.html", context)


@user_passes_test(lambda u: u.is_authenticated)
def analysis_module_configure(
    request: HttpRequest, workspace_pk: int, module_key: str
) -> HttpResponse:
    """Right-panel parameter form for one analysis, opened from its card."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = _get_active_scenario(request, workspace)
    meta = _get_analysis_meta(module_key)
    form = AnalysisModuleForm(workspace=workspace, scenario=scenario, module=module_key)
    return render(
        request,
        "workspace/analysis/_module_form.html",
        {"workspace": workspace, "scenario": scenario, "analysis": meta, "form": form},
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def analysis_module_launch(
    request: HttpRequest, workspace_pk: int, module_key: str
) -> HttpResponse:
    """Launch one analysis in the background and notify immediately.

    Creates the ``AnalysisRun`` and dispatches it to Celery via
    ``launch_analysis_run`` — the request never blocks on the analysis
    itself finishing. The response fires a toast right away and swaps the
    right panel to a status view; the analysis's card (see
    ``analysis_card_status``) polls independently until the run completes.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    meta = _get_analysis_meta(module_key)
    form = AnalysisModuleForm(request.POST, workspace=workspace, module=module_key)

    if not form.is_valid():
        return render(
            request,
            "workspace/analysis/_module_form.html",
            {"workspace": workspace, "scenario": None, "analysis": meta, "form": form},
            status=400,
        )

    scenario: Scenario = form.cleaned_data["scenario"]
    vars_ = form.build_vars(workspace)
    run = launch_analysis_run(
        workspace_id=workspace.pk,
        module_names=[module_key],
        vars_=vars_,
        scenario_id=scenario.pk,
    )

    html = render_to_string(
        "workspace/analysis/_module_launch_confirm.html",
        {"workspace": workspace, "scenario": scenario, "analysis": meta, "run": run},
        request=request,
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps(
        {"show-toast": f"{meta['label']} analysis started"},
    )
    return response
