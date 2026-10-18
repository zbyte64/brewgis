"""Views for launching and monitoring analysis pipeline runs."""

from __future__ import annotations

import json
import re
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

from brewgis.workspace.analysis.launch import AnalysisInputs
from brewgis.workspace.analysis.launch import AnalysisLaunchError
from brewgis.workspace.analysis.launch import launch_analysis
from brewgis.workspace.analysis.module_registry import CANONICAL_COLUMN_NAMES
from brewgis.workspace.analysis.module_registry import MODULE_LABELS
from brewgis.workspace.analysis.module_registry import get_available_analyses
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_module_parameters
from brewgis.workspace.analysis.module_registry import resolve_module_order
from brewgis.workspace.analysis.run_health import reconcile_abandoned_run
from brewgis.workspace.analysis.run_health import reconcile_abandoned_runs
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.views.built_forms import HtmxResponseMixin


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
        _add_scenario_input_fields(
            self, constraints=True, column_mapping=True, scenario=scenario
        )

    # Per-module analysis parameters are NOT offered here: this form launches
    # several modules at once, so a parameter cannot be scoped to one of them
    # (see ``AnalysisModuleForm``).

    def analysis_inputs(self) -> AnalysisInputs:
        """The inputs this submission sets on the scenario before its run."""
        return _scenario_inputs_from_form(self)


# One editable row per configured constraint plus one blank row for adding
# another. Rows are plain form fields (``constraint_<n>_table`` / ``_geom_col``
# / ``_discount_pct``), so crispy renders them in both analysis forms' templates.
_CONSTRAINT_FIELD = re.compile(r"constraint_(\d+)_(?:table|geom_col|discount_pct)")


def _constraint_row_count(form: forms.Form, scenario: Scenario | None) -> int:
    """Rows to build: every submitted row when bound, else the stored ones + 1."""
    if form.is_bound:
        indices = {
            int(match.group(1))
            for key in form.data
            if (match := _CONSTRAINT_FIELD.fullmatch(key))
        }
        return max(indices, default=-1) + 1
    stored = (scenario.constraints or []) if scenario is not None else []
    return len(stored) + 1


def _add_scenario_input_fields(
    form: forms.Form,
    *,
    constraints: bool,
    column_mapping: bool,
    scenario: Scenario | None = None,
) -> None:
    """Add the constraint and column-mapping fields to *form*.

    Shared by both analysis forms so their field definitions can never drift
    apart: the full-page multi-module launcher always shows them, while a
    single-module form shows them only when the module's dependency chain
    actually resolves through ``env_constraint`` / ``core``.

    The constraint rows edit the scenario's own ``Scenario.constraints`` — the
    same ``{table, discount_pct, geom_col}`` list the MCP ``run_analysis`` tool
    takes — so any configuration one launcher can set, the other can show and
    keep. Validation and defaults live in
    :func:`brewgis.workspace.analysis.launch.launch_analysis`.
    """
    if constraints:
        stored = (scenario.constraints or []) if scenario is not None else []
        for index in range(_constraint_row_count(form, scenario)):
            entry = stored[index] if index < len(stored) else {}
            number = index + 1
            form.fields[f"constraint_{index}_table"] = forms.CharField(
                required=False,
                initial=entry.get("table", ""),
                label=f"Constraint {number} table",
                help_text=(
                    "Polygon table, schema-qualified (e.g. fresno.floodplains); a bare "
                    "name resolves in public. Clear it to remove the constraint."
                ),
            )
            form.fields[f"constraint_{index}_geom_col"] = forms.CharField(
                required=False,
                initial=entry.get("geom_col", ""),
                label=f"Constraint {number} geometry column",
                help_text="Defaults to geom.",
            )
            form.fields[f"constraint_{index}_discount_pct"] = forms.FloatField(
                required=False,
                min_value=0,
                max_value=100,
                initial=entry.get("discount_pct"),
                label=f"Constraint {number} discount %",
                help_text="% of the overlapping acreage excluded from developable land. Defaults to 100.",
            )
    if column_mapping:
        for name in CANONICAL_COLUMN_NAMES:
            form.fields[f"column_{name}"] = forms.CharField(
                required=False,
                label=f"{name.replace('_', ' ').title()} column override",
                help_text=f"Use if your source table names this column something other than '{name}'.",
            )


def _scenario_inputs_from_form(
    form: forms.Form, params: dict[str, Any] | None = None
) -> AnalysisInputs:
    """Translate a validated analysis form into :class:`AnalysisInputs`.

    A section the form does not render (constraints or column mapping, for a
    module whose chain does not read them) is ``None`` — the scenario keeps its
    stored value. A rendered section replaces it: constraint rows with a blank
    table are dropped, and blank geometry/discount cells are left out so the
    launch service applies its defaults.
    """
    constraints: list[dict[str, Any]] | None = None
    if "constraint_0_table" in form.fields:
        constraints = []
        index = 0
        while f"constraint_{index}_table" in form.fields:
            table = form.cleaned_data.get(f"constraint_{index}_table")
            if table:
                entry: dict[str, Any] = {"table": table}
                geom_col = form.cleaned_data.get(f"constraint_{index}_geom_col")
                if geom_col:
                    entry["geom_col"] = geom_col
                discount = form.cleaned_data.get(f"constraint_{index}_discount_pct")
                if discount is not None:
                    entry["discount_pct"] = discount
                constraints.append(entry)
            index += 1
    column_mapping: dict[str, str] | None = None
    if f"column_{CANONICAL_COLUMN_NAMES[0]}" in form.fields:
        column_mapping = {
            name: form.cleaned_data[f"column_{name}"]
            for name in CANONICAL_COLUMN_NAMES
            if form.cleaned_data.get(f"column_{name}")
        }
    return AnalysisInputs(
        constraints=constraints, column_mapping=column_mapping, params=params or {}
    )


def _add_launch_errors(form: forms.Form, error: AnalysisLaunchError) -> None:
    """Report a refused launch on *form* as form-level errors."""
    for preflight_error in error.errors:
        form.add_error(None, preflight_error.message)


def _add_parameter_fields(form: forms.Form, module: str, scenario: Scenario) -> None:
    """Add *module*'s analysis-parameter fields, initialized from the scenario.

    One field per ``module_registry.ANALYSIS_PARAMETERS`` entry whose
    ``modules`` include *module*: the value the scenario has stored, falling
    back to the parameter's default. The values are stored on the scenario by
    ``launch.launch_analysis`` and baked into the scenario's model blueprints.
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
    than entered — see ``launch.scenario_analysis_errors``.
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
            scenario=scenario,
        )
        _add_parameter_fields(self, module, scenario)

        self.helper = FormHelper()
        self.helper.form_tag = False

        if self._workspace:
            self.fields["scenario"].initial = scenario.pk

            self.fields["scenario"].queryset = Scenario.objects.filter(  # type: ignore[attr-defined]
                workspace=self._workspace,
            )

    def analysis_inputs(self) -> AnalysisInputs:
        """The inputs this submission sets on the scenario before its run.

        A parameter whose field came back empty is left out (the scenario keeps
        its value) — except a ``str`` parameter, whose empty value *is* its
        "unset" value and is therefore sent as-is.
        """
        params = {
            param.name: self.cleaned_data[param.name]
            for param in get_module_parameters(self._module)
            if self.cleaned_data.get(param.name) is not None
        }
        return _scenario_inputs_from_form(self, params)


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
        try:
            run = launch_analysis(
                scenario=data["scenario"],
                modules=modules,
                inputs=form.analysis_inputs(),
            )
        except AnalysisLaunchError as error:
            _add_launch_errors(form, error)
            return self.form_invalid(form)

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


def _vmt_fee_data(run: AnalysisRun) -> dict[str, float] | None:
    """Return the run's VMT fee totals, or None when the run has none to show.

    Only a completed run whose modules include ``vmt_fee`` has a fee table to
    read; the table itself is per-scenario and may not exist yet, which is not
    a render failure — the detail view simply omits the fee block.
    """
    if run.status != "completed" or "vmt_fee" not in (run.modules or []):
        return None
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
    except Exception:
        return None
    if not row:
        return None
    return {
        "revenue": round(row[0], 2),
        "revenue_forgone": round(row[1], 2),
        "vmt_exempt": round(row[2], 2),
    }


def analysis_status(request: HttpRequest, run_pk: int) -> HttpResponse:
    """Analysis run detail — full page on a direct visit, htmx-polled partial otherwise."""
    run = get_object_or_404(AnalysisRun, pk=run_pk)
    # Polled every 2s while the run reads as live, so this is where a run whose
    # worker died gets recorded as failed and the poll stops.
    reconcile_abandoned_run(run)

    template_name = (
        "workspace/analysis/status.html#analysis-status"
        if request.htmx  # type: ignore[attr-defined]
        else "workspace/analysis/status.html"
    )
    return render(
        request,
        template_name,
        {"run": run, "vmt_fee_data": _vmt_fee_data(run)},
    )


@user_passes_test(lambda u: u.is_authenticated)
def analysis_list(request: HttpRequest) -> HttpResponse:
    """List recent analysis runs for the current user's workspaces."""
    runs = AnalysisRun.objects.select_related("workspace").order_by("-created_at")[:50]
    reconcile_abandoned_runs(runs)
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


def _module_parameter_rows(
    scenario: Scenario | None, module_key: str
) -> list[dict[str, Any]]:
    """Return the active parameter values a rematerialization reads for *module_key*.

    One row per ``module_registry.ANALYSIS_PARAMETERS`` entry the module owns:
    the scenario's override when it has one, otherwise the registry default.
    That is the same merge ``AnalysisModuleForm`` writes to the scenario and
    ``sqlmesh/macros/analysis_blueprints.py`` bakes into the models' blueprints,
    so these rows are the inputs a rerun or a direct SQLMesh plan will use —
    which is what makes them worth showing next to a layer whose view may have
    been built outside the Analysis panel.
    """
    overrides = (scenario.analysis_params or {}) if scenario is not None else {}
    return [
        {
            "name": param.name,
            "value": overrides.get(param.name, param.default),
            "overridden": param.name in overrides,
        }
        for param in get_module_parameters(module_key)
    ]


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


def _module_last_run(
    workspace: Workspace, scenario: Scenario | None, module_key: str
) -> AnalysisRun | None:
    """Return the newest run that included *module_key*, scoped like the cards.

    A module's card and the details it opens both read this one definition of
    "its last run", so the badge and the details can never disagree. The run is
    reconciled before it is returned: the card polls this every 2s while the run
    reads as live, so a run whose worker died is recorded as failed here and the
    poll ends (see :mod:`brewgis.workspace.analysis.run_health`).
    """
    runs = AnalysisRun.objects.filter(workspace=workspace).select_related("scenario")
    if scenario is not None:
        runs = runs.filter(scenario=scenario)
    run = runs.filter(modules__contains=[module_key]).order_by("-created_at").first()
    return None if run is None else reconcile_abandoned_run(run)


def _analysis_card_context(
    workspace: Workspace,
    scenario: Scenario | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Build the render context for one analysis's card.

    Shared by the card-list panel and the single-card polling endpoint so
    both always render identical markup.
    """
    return {
        "workspace": workspace,
        "scenario": scenario,
        "analysis": meta,
        "last_run": _module_last_run(workspace, scenario, meta["key"]),
    }


@user_passes_test(lambda u: u.is_authenticated)
def panel_analysis_card_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Left-sidebar Analysis panel — a card per available analysis module, each
    carrying its own last run."""
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
def analysis_module_details(
    request: HttpRequest, workspace_pk: int, module_key: str
) -> HttpResponse:
    """One analysis module's last run, rendered into its card in the map view.

    Reuses the run-detail fragment the status page and the launch response
    render, so the map's Analysis panel shows the same modules, timings, run
    parameters, failure cause, traceback and log — and keeps polling while the
    run is active — without sending the user off the map. An analysis that has
    never run has no details, so it renders as nothing.

    ``?panel=1`` is the right-drawer presentation of the same thing, opened by
    a layer's per-analysis icon in the Layers panel: the module is named and
    described above the *active inputs a rematerialization reads* — the
    scenario's parameter overrides, constraint discounts and column mapping,
    which is what ``sqlmesh/macros/analysis_blueprints.py`` bakes into the
    models when they are (re)rendered — followed by the run responsible when
    one is recorded, or a note that the view was published outside the Analysis
    panel. The layer is shown either way: its view exists and is being tiled,
    whether or not a run row survives.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    meta = _get_analysis_meta(module_key)
    scenario = _get_active_scenario(request, workspace)
    run = _module_last_run(workspace, scenario, module_key)

    if request.GET.get("panel") == "1":
        return render(
            request,
            "workspace/analysis/_analysis_module_panel.html",
            {
                "workspace": workspace,
                "scenario": scenario,
                "analysis": meta,
                "run": run,
                "vmt_fee_data": _vmt_fee_data(run) if run else None,
                "parameters": _module_parameter_rows(scenario, module_key),
                "constraints": (scenario.constraints or []) if scenario else [],
                "column_mapping": ((scenario.column_mapping or {}) if scenario else {}),
            },
        )

    if run is None:
        return HttpResponse("")
    return render(
        request,
        "workspace/analysis/_analysis_details.html",
        {"analysis": meta, "run": run, "vmt_fee_data": _vmt_fee_data(run)},
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
    return _launch_module(
        request,
        meta=meta,
        scenario=form.cleaned_data["scenario"],
        inputs=form.analysis_inputs(),
        form=form,
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def analysis_module_rerun(
    request: HttpRequest, workspace_pk: int, module_key: str
) -> HttpResponse:
    """Launch one analysis again with exactly the inputs stored on its scenario.

    A run's inputs live on the Scenario (see ``launch.launch_analysis``), so a
    rerun sets none: it posts only the scenario. A rerun the launch service
    refuses (a constraint table that no longer exists, say) opens the module's
    parameter form with the reasons, where the stored inputs can be corrected.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    meta = _get_analysis_meta(module_key)
    scenario = get_object_or_404(
        Scenario, pk=request.POST.get("scenario"), workspace=workspace
    )
    form = AnalysisModuleForm(workspace=workspace, scenario=scenario, module=module_key)
    return _launch_module(
        request,
        meta=meta,
        scenario=scenario,
        inputs=AnalysisInputs(),
        form=form,
    )


def _launch_module(
    request: HttpRequest,
    *,
    meta: dict[str, Any],
    scenario: Scenario,
    inputs: AnalysisInputs,
    form: AnalysisModuleForm,
) -> HttpResponse:
    """Launch *meta*'s module for *scenario*; on refusal re-render *form* with why."""
    try:
        run = launch_analysis(scenario=scenario, modules=[meta["key"]], inputs=inputs)
    except AnalysisLaunchError as error:
        return render(
            request,
            "workspace/analysis/_module_form.html",
            {
                "workspace": scenario.workspace,
                "scenario": scenario,
                "analysis": meta,
                "form": form,
                "launch_errors": [e.message for e in error.errors],
            },
            status=400,
        )

    html = render_to_string(
        "workspace/analysis/status.html#analysis-status",
        {"run": run, "vmt_fee_data": None},
        request=request,
    )
    response = HttpResponse(html)
    response["HX-Trigger"] = json.dumps(
        {"show-toast": f"{meta['label']} analysis started"},
    )
    return response
