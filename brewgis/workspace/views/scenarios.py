"""Views for scenario management and comparison."""

from __future__ import annotations

import json
import uuid

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import County
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import create_canvas_view
from brewgis.workspace.services.scenario_cloner import clone_scenario

# ---------------------------------------------------------------------------
# ScenarioCreateForm
# ---------------------------------------------------------------------------


class ScenarioCreateForm(forms.Form):
    """Standard form (not ModelForm) — parent field needs custom queryset."""

    name = forms.CharField(
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    scenario_type = forms.ChoiceField(
        choices=ScenarioType.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    parent = forms.ModelChoiceField(
        queryset=Scenario.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    base_year = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    horizon_year = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    def __init__(
        self, *args: object, workspace: Workspace | None = None, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)
        if workspace is not None:
            self.fields["parent"].queryset = Scenario.objects.filter(
                workspace=workspace,
                scenario_type=ScenarioType.BASE,
            )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean()
        base_year = cleaned.get("base_year")
        horizon_year = cleaned.get("horizon_year")
        scenario_type = cleaned.get("scenario_type")
        parent = cleaned.get("parent")

        if (
            base_year is not None
            and horizon_year is not None
            and base_year >= horizon_year
        ):
            self.add_error("horizon_year", "Horizon year must be after base year.")

        if scenario_type == ScenarioType.ALTERNATIVE and parent is None:
            self.add_error(
                "parent", "Alternative scenarios must have a parent base scenario."
            )

        if scenario_type == ScenarioType.BASE and parent is not None:
            cleaned["parent"] = None

        return cleaned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_comparison_metrics(scenario: Scenario) -> dict[str, float | int | None]:
    """Query aggregate metrics for a *scenario* via its canvas view."""

    metrics: dict[str, float | int | None] = {
        "total_population": 0,
        "total_households": 0,
        "total_du": 0,
        "total_employment": 0,
        "total_vmt": None,
        "total_water": None,
        "total_energy": None,
        "total_land_consumed_acres": 0,
    }

    # Canvas view aggregate query — gracefully return zeroes if view missing
    schema = scenario.target_schema
    view_name = f"scenario_{scenario.slug}_canvas"
    q_view = f'"{schema}"."{view_name}"'

    try:
        with transaction.savepoint(using="default"), connection.cursor() as cursor:
            cursor.execute(
                f"""
                    SELECT
                        COALESCE(SUM(pop), 0),
                        COALESCE(SUM(hh), 0),
                        COALESCE(SUM(du), 0),
                        COALESCE(SUM(emp), 0),
                        COALESCE(SUM(area_acres), 0)
                    FROM {q_view}
                    """
            )
            row = cursor.fetchone()
            if row:
                metrics["total_population"] = row[0] or 0
                metrics["total_households"] = row[1] or 0
                metrics["total_du"] = row[2] or 0
                metrics["total_employment"] = row[3] or 0
                metrics["total_land_consumed_acres"] = row[4] or 0
    except Exception:
        pass  # view does not exist yet — keep zero defaults

    # Analysis-run metrics from the most recent completed run
    latest_run = (
        AnalysisRun.objects.filter(scenario=scenario, status="completed")
        .order_by("-created_at")
        .first()
    )
    if latest_run is not None and latest_run.vars:
        metrics["total_vmt"] = latest_run.vars.get("total_vmt")
        metrics["total_water"] = latest_run.vars.get(
            "total_water"
        ) or latest_run.vars.get("total_water_demand")
        metrics["total_energy"] = latest_run.vars.get(
            "total_energy"
        ) or latest_run.vars.get("total_energy_demand")

    return metrics


def _build_layer_data(workspace: Workspace) -> list[dict[str, object]]:
    """Build per-scenario layer data (same logic as map.py)."""
    from brewgis.workspace.models import SymbologyConfig
    from brewgis.workspace.symbology.generator import generate_maplibre_style
    from brewgis.workspace.views.map import LayerSchema

    layer_data: list[dict[str, object]] = []
    for layer in workspace.layers.all():
        data = LayerSchema.model_validate(layer).model_dump()
        data["source"] = layer.to_maplibre_source()
        # Merge symbology-generated paint/layout if available
        try:
            config = layer.symbology
            style = generate_maplibre_style(config)
            data["paint"] = style["paint"]
            data["layout"] = style["layout"]
        except SymbologyConfig.DoesNotExist:
            pass
        layer_data.append(data)
    return layer_data


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@user_passes_test(lambda u: u.is_authenticated)
def scenario_create(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Create a new scenario. GET returns the form; POST saves and redirects."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    if request.method == "POST":
        form = ScenarioCreateForm(request.POST, workspace=workspace)
        if form.is_valid():
            scenario = Scenario.objects.create(
                workspace=workspace,
                name=form.cleaned_data["name"],
                description=form.cleaned_data.get("description", ""),
                scenario_type=form.cleaned_data["scenario_type"],
                parent=form.cleaned_data.get("parent"),
                base_year=form.cleaned_data["base_year"],
                horizon_year=form.cleaned_data["horizon_year"],
            )
            create_canvas_view(scenario, base_table="public.base_canvas")
            return redirect("workspace:workspace_detail", pk=workspace.pk)
    else:
        form = ScenarioCreateForm(workspace=workspace)

    context: dict[str, object] = {
        "workspace": workspace,
        "form": form,
    }
    return render(request, "workspace/scenario_form.html", context)


@user_passes_test(lambda u: u.is_authenticated)
def scenario_edit(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> HttpResponse:
    """Edit an existing scenario's metadata."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    if request.method == "POST":
        form = ScenarioCreateForm(request.POST, workspace=workspace)
        if form.is_valid():
            scenario.name = form.cleaned_data["name"]
            scenario.description = form.cleaned_data.get("description", "")
            scenario.base_year = form.cleaned_data["base_year"]
            scenario.horizon_year = form.cleaned_data["horizon_year"]
            scenario.save()
            return redirect("workspace:workspace_detail", pk=workspace.pk)
    else:
        initial = {
            "name": scenario.name,
            "description": scenario.description,
            "scenario_type": scenario.scenario_type,
            "parent": scenario.parent,
            "base_year": scenario.base_year,
            "horizon_year": scenario.horizon_year,
        }
        form = ScenarioCreateForm(initial=initial, workspace=workspace)

    context: dict[str, object] = {
        "workspace": workspace,
        "scenario": scenario,
        "form": form,
    }
    return render(request, "workspace/scenario_form.html", context)


@user_passes_test(lambda u: u.is_authenticated)
def scenario_delete(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse | HttpResponse:
    """Delete a scenario. POST only; returns JSON."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)
    scenario.delete()
    return JsonResponse({"status": "ok"})


@user_passes_test(lambda u: u.is_authenticated)
def scenario_clone(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse | HttpResponse:
    """Clone a scenario. POST only; accepts JSON body with name (required) and description."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    source = get_object_or_404(Scenario, pk=scenario_pk, workspace=workspace)

    body = json.loads(request.body)
    name = body.get("name")
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)

    description = body.get("description", "")
    new_scenario = clone_scenario(source=source, name=name, description=description)

    return JsonResponse(
        {
            "status": "ok",
            "scenario": {
                "pk": new_scenario.pk,
                "name": new_scenario.name,
                "slug": new_scenario.slug,
            },
        }
    )


@user_passes_test(lambda u: u.is_authenticated)
def scenario_comparison(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Render a scenario comparison page."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    scenario_pks_param = request.GET.get("scenarios", "")
    scenario_pks = [
        int(pk.strip()) for pk in scenario_pks_param.split(",") if pk.strip()
    ]

    scenarios = list(Scenario.objects.filter(pk__in=scenario_pks, workspace=workspace))

    # Per-scenario layer data and metrics
    layer_data: dict[str, list[dict[str, object]]] = {}
    metrics_data: list[dict[str, object]] = []
    for sc in scenarios:
        layer_data[sc.slug] = _build_layer_data(workspace)
        metrics = _build_comparison_metrics(sc)
        metrics.update({"id": sc.pk, "name": sc.name, "slug": sc.slug})
        metrics_data.append(metrics)

    county_q = _build_county_q(workspace)
    counties = County.objects.filter(county_q) if county_q else County.objects.none()

    context: dict[str, object] = {
        "workspace": workspace,
        "scenarios": scenarios,
        "scenarios_json": json.dumps(
            [
                {
                    "id": s.pk,
                    "name": s.name,
                    "slug": s.slug,
                    "scenario_type": s.scenario_type,
                }
                for s in scenarios
            ]
        ),
        "layer_data": layer_data,
        "counties": counties,
    }
    return render(request, "workspace/scenario_comparison.html", context)


@user_passes_test(lambda u: u.is_authenticated)
def scenario_comparison_data(request: HttpRequest, workspace_pk: int) -> JsonResponse:
    """JSON endpoint returning per-scenario aggregate metrics."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    scenario_pks_param = request.GET.get("scenarios", "")
    scenario_pks = [
        int(pk.strip()) for pk in scenario_pks_param.split(",") if pk.strip()
    ]

    scenarios = list(Scenario.objects.filter(pk__in=scenario_pks, workspace=workspace))

    result_scenarios: list[dict[str, object]] = []
    for sc in scenarios:
        metrics = _build_comparison_metrics(sc)
        result_scenarios.append(
            {
                "id": sc.pk,
                "name": sc.name,
                "slug": sc.slug,
                "metrics": metrics,
            }
        )

    return JsonResponse({"status": "ok", "scenarios": result_scenarios})


def _build_county_q(workspace: Workspace) -> object:
    """Build a Q object for filtering counties from workspace county_fips_list."""
    from django.db.models import Q

    county_q = Q()
    for entry in workspace.county_fips_list:
        county_q |= Q(
            state_fips=entry["state"],
            county_fips=entry["county"],
        )
    return county_q


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def scenario_toggle_publish(
    request: HttpRequest, workspace_pk: int, scenario_pk: int
) -> JsonResponse:
    """Toggle the published state of a scenario."""
    scenario = get_object_or_404(Scenario, pk=scenario_pk, workspace_id=workspace_pk)
    scenario.published = not scenario.published
    if scenario.published and scenario.public_token is None:
        scenario.public_token = uuid.uuid4()
    scenario.save(update_fields=["published", "public_token"])
    return JsonResponse(
        {
            "status": "ok",
            "published": scenario.published,
            "public_token": str(scenario.public_token)
            if scenario.public_token
            else None,
        }
    )
