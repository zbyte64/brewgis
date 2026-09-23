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
from brewgis.workspace.analysis.module_registry import get_module_parameters
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.pipeline import launch_analysis_run
from brewgis.workspace.analysis.pipeline import run_analysis_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import PreflightError
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.views.built_forms import HtmxResponseMixin

_BUILT_FORMS_TABLE = "built_forms"
"""Table the analysis models read BuildingType definitions from.

Schema-qualified with ``Workspace.db_schema`` on both sides — here and in
``sqlmesh/macros/analysis_blueprints.py``, which bakes the same name into the
scenario's model blueprints.
"""


def scenario_analysis_errors(
    workspace: Workspace, scenario: Scenario
) -> list[PreflightError]:
    """Return the blocking prerequisite errors for analyzing *scenario*.

    The analysis models derive everything they read from the scenario and its
    workspace (see ``sqlmesh/macros/analysis_blueprints.py``), so those derived
    inputs are what a launch is validated against — not values typed into a
    form:

    - the scenario's own parcel source: its canvas view for an ALTERNATIVE
      scenario (base canvas + painted edits), the workspace's base canvas
      otherwise (``Scenario.base_layer_table``);
    - the workspace's exported built-forms table, which is mechanically
      re-synced from the configured ``BuildingType`` rows first. That sync never
      invents data — a workspace with no BuildingType rows still produces an
      empty table, which the check below reports.

    The export sync uses its own DB connection (not Django's request-scoped
    one) so the write commits immediately: under ATOMIC_REQUESTS the whole view
    runs in one transaction, but SQLMesh's engine adapter opens a separate
    connection to run the plan — it can't see this table until it's actually
    committed, not just pending in our own txn.
    """
    ensure_export_exists_isolated(
        workspace, schema=workspace.db_schema, table=_BUILT_FORMS_TABLE
    )
    return check_analysis_prerequisites(
        schema=workspace.db_schema,
        parcel_table=scenario.base_layer_table,
        built_form_table=_BUILT_FORMS_TABLE,
        base_canvas_table=workspace.base_table,
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
        help_text=(
            "Select a scenario for this analysis run. Its parcel source and "
            "the parameters below are stored on the scenario, so rerunning it "
            "— from here or from the map's Analysis panel — uses the same "
            "inputs."
        ),
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize form, defaulting the scenario to the workspace's own."""
        self._workspace: Workspace | None = cast(
            "Workspace | None", kwargs.pop("workspace", None)
        )
        # Required whenever `workspace` is given (see call sites, which
        # always fall back to the workspace's BASE scenario). Left
        # unenforced at the kwargs.pop() level so the rare workspace-less
        # instantiation (the bare "Run Analysis" picker page) still works,
        # since scenario is only read below inside `if self._workspace:`.
        scenario: Scenario = cast("Scenario", kwargs.pop("scenario", None))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        self.helper = FormHelper()
        self.helper.form_tag = False

        if self._workspace:
            self.fields["workspace"].queryset = Workspace.objects.filter(
                pk=self._workspace.pk,
            )
            self.fields["workspace"].initial = self._workspace.pk
            self.fields["workspace"].widget = forms.HiddenInput()

            self.fields["scenario"].initial = scenario.pk

            # Filter scenario queryset to the selected workspace
            self.fields["scenario"].queryset = Scenario.objects.filter(  # type: ignore[attr-defined]
                workspace=self._workspace,
            )

        # The parcel/built-form/base-canvas tables are derived per scenario by
        # the model blueprints, but constraints and column mapping are per-run
        # inputs — explicit fields, never JSON.
        _add_scenario_input_fields(self, constraints=True, column_mapping=True)

    # Constraint-discount and column-mapping fields are added in ``__init__``
    # (from ``_CONSTRAINT_LAYERS`` / ``CANONICAL_COLUMN_NAMES``, the same
    # fields ``AnalysisModuleForm`` builds), so this multi-module launcher no
    # longer requires typing JSON. Per-module analysis parameters are NOT
    # offered here: this form launches several modules at once, so a parameter
    # cannot be scoped to one of them (see ``AnalysisModuleForm``).

    def scenario_constraints(self) -> list[dict[str, Any]]:
        """Constraint layers to persist on the scenario for this run."""
        return [
            {"table": table, "discount_pct": data, "geom_col": geom_col}
            for field_name, table, geom_col, _default_pct in _CONSTRAINT_LAYERS
            if (data := self.cleaned_data.get(field_name)) is not None
        ]

    def scenario_column_mapping(self) -> dict[str, str]:
        """Parcel column mapping to persist on the scenario for this run."""
        return {
            name: self.cleaned_data[f"column_{name}"]
            for name in CANONICAL_COLUMN_NAMES
            if self.cleaned_data.get(f"column_{name}")
        }

    def clean(self) -> dict[str, Any] | None:
        """Validate analysis prerequisites before launching."""
        data = super().clean()
        if self.errors:
            return data
        if data is None:
            return None

        workspace: Workspace | None = data.get("workspace")
        scenario: Scenario | None = data.get("scenario")
        if workspace and scenario:
            # The checked tables are derived from the scenario and its
            # workspace (they are no longer form inputs), so every failure is
            # reported as a form-level error.
            for error in scenario_analysis_errors(workspace, scenario):
                self.add_error(None, error.message)

        return data


# Fixed constraint layers offered as individual discount-% fields on both
# analysis forms, so neither requires typing JSON. Each entry is
# field_name, table, geom_col, default_pct.
_CONSTRAINT_LAYERS: list[tuple[str, str, str, int]] = [
    ("floodplain_discount_pct", "floodplains", "geom", 100),
    ("wetlands_discount_pct", "wetlands", "geom", 100),
    ("steep_slopes_discount_pct", "steep_slopes", "geom", 75),
]


def _add_scenario_input_fields(
    form: forms.Form, *, constraints: bool, column_mapping: bool
) -> None:
    """Add the constraint-discount and column-mapping fields to *form*.

    Shared by both analysis forms so their field definitions can never drift
    apart: the full-page multi-module launcher always shows them, while a
    single-module form shows them only when the module's dependency chain
    actually resolves through ``env_constraint`` / ``core``.
    """
    if constraints:
        for field_name, table, _geom_col, default_pct in _CONSTRAINT_LAYERS:
            form.fields[field_name] = forms.IntegerField(
                required=False,
                min_value=0,
                max_value=100,
                initial=default_pct,
                label=f"{table.replace('_', ' ').title()} discount %",
                help_text="% of this layer's overlapping acreage excluded from developable land.",
            )
    if column_mapping:
        for name in CANONICAL_COLUMN_NAMES:
            form.fields[f"column_{name}"] = forms.CharField(
                required=False,
                label=f"{name.replace('_', ' ').title()} column override",
                help_text=f"Use if your source table names this column something other than '{name}'.",
            )


def _add_parameter_fields(form: forms.Form, module: str, scenario: Scenario) -> None:
    """Add *module*'s analysis-parameter fields, initialized from the scenario.

    One field per ``module_registry.ANALYSIS_PARAMETERS`` entry whose
    ``modules`` include *module*: the value the scenario has stored, falling
    back to the parameter's default. The values are persisted by
    ``AnalysisModuleForm.apply_scenario_params`` and baked into the scenario's
    model blueprints.
    """
    field_classes: dict[str, type[forms.Field]] = {
        "float": forms.FloatField,
        "bool": forms.BooleanField,
        "str": forms.CharField,
    }
    for param in get_module_parameters(module):
        current = (scenario.analysis_params or {}).get(param.name, param.default)
        form.fields[param.name] = field_classes[param.kind](
            required=False,
            initial=current,
            label=param.name.replace("_", " ").title(),
            help_text=f"Default: {param.default}",
        )


class AnalysisModuleForm(forms.Form):
    """Parameter form for launching a single analysis from its map-view card.

    Unlike ``AnalysisLaunchForm`` (a generic multi-module launcher), this form
    is bound to one specific analysis module and exposes every relevant
    parameter as its own field — no JSON entry required.

    It collects the parameters a run can still act on: which scenario to run
    against, how to discount constraint layers, how the scenario's parcel
    source names the canonical columns, and that scenario's analysis
    parameters (``module_registry.ANALYSIS_PARAMETERS``). The parcel/built-form/
    base-canvas tables are derived
    (``sqlmesh/macros/analysis_blueprints.py``), so they are validated rather
    than entered — see ``scenario_analysis_errors``.
    """

    scenario = forms.ModelChoiceField(
        queryset=Scenario.objects.all(),
        required=True,
        label="Scenario",
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the form for one ``module``, adding only its relevant fields."""
        self._workspace: Workspace | None = cast(
            "Workspace | None", kwargs.pop("workspace", None)
        )
        # Required whenever `workspace` is given — see AnalysisLaunchForm
        # for why this isn't enforced at the kwargs.pop() level.
        scenario: Scenario = cast("Scenario", kwargs.pop("scenario", None))
        module: str = cast("str", kwargs.pop("module"))
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        self._module = module
        deps = resolve_module_order([module])

        _add_scenario_input_fields(
            self,
            constraints="env_constraint" in deps,
            column_mapping="core" in deps,
        )
        _add_parameter_fields(self, module, scenario)

        self.helper = FormHelper()
        self.helper.form_tag = False

        if self._workspace:
            self.fields["scenario"].initial = scenario.pk

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
        scenario: Scenario | None = data.get("scenario")
        if workspace and scenario:
            for error in scenario_analysis_errors(workspace, scenario):
                self.add_error(None, error.message)

        return data

    def apply_scenario_params(self, scenario: Scenario) -> None:
        """Persist this run's parameters onto *scenario*.

        The analysis models are blueprinted per scenario, so a run's inputs are
        read from the Scenario at model-load time (see
        ``sqlmesh/macros/analysis_blueprints.py``) — persisting them here is
        what makes this launch, and any later rerun, use the same parameters.

        Analysis parameters are *merged* rather than replaced: a module's form
        only exposes its own parameters, so saving one must not discard the
        values another module's run stored. A parameter whose field came back
        empty is skipped — except a ``str`` parameter, whose empty value *is*
        its "unset" value and is therefore stored as-is.
        """
        constraints = [
            {"table": table, "discount_pct": data, "geom_col": geom_col}
            for field_name, table, geom_col, _default_pct in _CONSTRAINT_LAYERS
            if (data := self.cleaned_data.get(field_name)) is not None
        ]
        column_mapping = {
            name: self.cleaned_data[f"column_{name}"]
            for name in CANONICAL_COLUMN_NAMES
            if self.cleaned_data.get(f"column_{name}")
        }
        params = {
            param.name: self.cleaned_data[param.name]
            for param in get_module_parameters(self._module)
            if self.cleaned_data.get(param.name) is not None
        }
        scenario.constraints = constraints
        scenario.column_mapping = column_mapping
        scenario.analysis_params = {**scenario.analysis_params, **params}
        scenario.save(
            update_fields=["constraints", "column_mapping", "analysis_params"]
        )


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
        # uses to learn the map's currently-active scenario. Fall back to
        # the workspace's BASE scenario when none was explicitly picked —
        # every workspace always has exactly one.
        if workspace is not None:
            scenario_pk = self.request.GET.get("scenario")
            scenario = None
            if scenario_pk:
                scenario = Scenario.objects.filter(
                    pk=scenario_pk, workspace=workspace
                ).first()
            kwargs["scenario"] = scenario or workspace.scenarios.get(
                scenario_type=ScenarioType.BASE
            )
        return kwargs

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Run Analysis"
        return context

    def form_valid(self, form: AnalysisLaunchForm) -> HttpResponse:
        data = form.cleaned_data
        modules: list[str] = data["modules"]
        scenario: Scenario = data["scenario"]

        # The models are blueprinted per scenario, so this run's parameters are
        # read off the Scenario when the plan loads it — persist them here.
        scenario.constraints = form.scenario_constraints()
        scenario.column_mapping = form.scenario_column_mapping()
        scenario.save(update_fields=["constraints", "column_mapping"])

        run = run_analysis_pipeline(
            scenario_id=scenario.pk,
            module_names=modules,
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
    scenario = _get_active_scenario(request, workspace) or workspace.scenarios.get(
        scenario_type=ScenarioType.BASE
    )
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
    # The bound form's actual `scenario` value comes from POST data (below);
    # this kwarg only seeds field.initial, which a bound form ignores — any
    # scenario belonging to the workspace is a safe placeholder here.
    default_scenario = _get_active_scenario(
        request, workspace
    ) or workspace.scenarios.get(scenario_type=ScenarioType.BASE)
    form = AnalysisModuleForm(
        request.POST, workspace=workspace, scenario=default_scenario, module=module_key
    )

    if not form.is_valid():
        return render(
            request,
            "workspace/analysis/_module_form.html",
            {"workspace": workspace, "scenario": None, "analysis": meta, "form": form},
            status=400,
        )

    scenario: Scenario = form.cleaned_data["scenario"]
    form.apply_scenario_params(scenario)
    run = launch_analysis_run(
        scenario_id=scenario.pk,
        module_names=[module_key],
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
