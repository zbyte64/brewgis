from __future__ import annotations

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.db.models import Q
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import County
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import DataSourceCategory
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.preflight import _qi
from brewgis.workspace.services.preflight import _table_exists

# Maps DataSource.import_type -> the URL name of the view that performs it.
# Sources without a mapped type here fall back to the generic Import Center.
_IMPORT_TYPE_URL_NAMES: dict[str, str] = {
    "census": "workspace:census_fetch",
    "lehd": "workspace:employment_fetch",
    "poi": "workspace:poi_fetch",
    "upload": "workspace:upload",
    "raster": "workspace:raster_upload",
}

# import_type values that require the user to supply their own file — there's
# no live integration with the listed provider (e.g. FEMA, USFWS, USGS), so
# the action must read "Upload", never "Import"/"Fetch", to avoid implying
# an automatic pull from that provider.
_MANUAL_UPLOAD_TYPES: frozenset[str] = frozenset({"upload", "raster"})

STATE_NAMES: dict[str, str] = {
    "01": "Alabama",
    "02": "Alaska",
    "04": "Arizona",
    "05": "Arkansas",
    "06": "California",
    "08": "Colorado",
    "09": "Connecticut",
    "10": "Delaware",
    "11": "District of Columbia",
    "12": "Florida",
    "13": "Georgia",
    "15": "Hawaii",
    "16": "Idaho",
    "17": "Illinois",
    "18": "Indiana",
    "19": "Iowa",
    "20": "Kansas",
    "21": "Kentucky",
    "22": "Louisiana",
    "23": "Maine",
    "24": "Maryland",
    "25": "Massachusetts",
    "26": "Michigan",
    "27": "Minnesota",
    "28": "Mississippi",
    "29": "Missouri",
    "30": "Montana",
    "31": "Nebraska",
    "32": "Nevada",
    "33": "New Hampshire",
    "34": "New Jersey",
    "35": "New Mexico",
    "36": "New York",
    "37": "North Carolina",
    "38": "North Dakota",
    "39": "Ohio",
    "40": "Oklahoma",
    "41": "Oregon",
    "42": "Pennsylvania",
    "44": "Rhode Island",
    "45": "South Carolina",
    "46": "South Dakota",
    "47": "Tennessee",
    "48": "Texas",
    "49": "Utah",
    "50": "Vermont",
    "51": "Virginia",
    "53": "Washington",
    "54": "West Virginia",
    "55": "Wisconsin",
    "56": "Wyoming",
}


ANALYSIS_MODULES: list[dict[str, object]] = [
    {
        "key": "env_constraint",
        "name": "Environmental Constraint",
        "description": "Overlay environmental constraints on base parcels",
        "inputs": ["Base parcels", "Constraint layers"],
        "outputs": ["Environmental constraint overlay"],
        "prereq_status": "",
    },
    {
        "key": "core",
        "name": "Core Allocation",
        "description": "End-state allocation plus increment analysis",
        "inputs": ["Scenario parameters", "Base allocation"],
        "outputs": ["End-state allocation", "Increment from base"],
        "prereq_status": "",
    },
    {
        "key": "water_demand",
        "name": "Water Demand",
        "description": "Residential and non-residential water demand in L/yr",
        "inputs": ["Allocated parcels", "Density factors"],
        "outputs": ["Water demand (L/yr)"],
        "prereq_status": "",
    },
    {
        "key": "energy_demand",
        "name": "Energy Demand",
        "description": "Residential and non-residential energy demand in kWh/yr",
        "inputs": ["Allocated parcels", "Density factors"],
        "outputs": ["Energy demand (kWh/yr)"],
        "prereq_status": "",
    },
]

# Constraint tables checked by the analysis launch form's default configuration
# (see AnalysisLaunchForm._CONSTRAINTS_INITIAL in views/analysis.py).
_CONSTRAINT_LAYER_TABLES: tuple[str, ...] = ("floodplains", "wetlands", "steep_slopes")


def _split_table_ref(schema: str, table_ref: str) -> tuple[str, str]:
    """Split a possibly schema-qualified "schema.table" reference."""
    if "." in table_ref:
        table_schema, table_name = table_ref.split(".", 1)
        return table_schema, table_name
    return schema, table_ref


def _table_has_rows(schema: str, table: str) -> bool:
    """Return True if schema.table exists in Postgres and has at least one row."""
    with connection.cursor() as cursor:
        if not _table_exists(cursor, schema, table):
            return False
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {_qi(schema, table)})")
        (has_rows,) = cursor.fetchone()
        return bool(has_rows)


def _prereq_status(*inputs_ready: bool) -> str:
    """Reduce a module's per-input readiness booleans to a prereq_status."""
    if all(inputs_ready):
        return "ready"
    if any(inputs_ready):
        return "partial"
    return ""


def build_analysis_modules(workspace: Workspace) -> list[dict[str, object]]:
    """Return ANALYSIS_MODULES with prereq_status computed from real data.

    Checks the actual tables/rows each module's inputs describe, scoped to
    this workspace, rather than the previous hardcoded empty status.
    """
    base_schema, base_name = _split_table_ref(workspace.db_schema, workspace.base_table)
    base_parcels_ready = _table_has_rows(base_schema, base_name)
    constraint_layers_ready = any(
        _table_has_rows(workspace.db_schema, table)
        for table in _CONSTRAINT_LAYER_TABLES
    )
    scenario_ready = Scenario.objects.filter(workspace=workspace).exists()
    allocated_parcels_ready = AnalysisRun.objects.filter(
        workspace=workspace,
        status="completed",
        modules__contains=["core"],
    ).exists()
    density_factors_ready = BuildingType.objects.filter(workspace=workspace).exists()

    water_energy_status = _prereq_status(allocated_parcels_ready, density_factors_ready)
    status_by_key: dict[str, str] = {
        "env_constraint": _prereq_status(base_parcels_ready, constraint_layers_ready),
        "core": _prereq_status(scenario_ready, base_parcels_ready),
        "water_demand": water_energy_status,
        "energy_demand": water_energy_status,
    }

    modules = [dict(module) for module in ANALYSIS_MODULES]
    for module in modules:
        module["prereq_status"] = status_by_key[module["key"]]
    return modules


def _build_region_summary(workspace: Workspace) -> str:
    """Build a human-readable region summary from the workspace county list."""
    entries = workspace.county_fips_list
    if not entries:
        return ""

    states = {entry.get("state", "") for entry in entries}

    if len(entries) == 1:
        entry = entries[0]
        county_obj = County.objects.filter(
            state_fips=entry.get("state", ""),
            county_fips=entry.get("county", ""),
        ).first()
        if county_obj:
            state_name = STATE_NAMES.get(entry.get("state", ""), entry.get("state", ""))
            return f"{county_obj.name} County, {state_name}"

    if len(states) == 1:
        state_fips = next(iter(states))
        state_name = STATE_NAMES.get(state_fips, state_fips)
        return f"{len(entries)} counties, {state_name}"

    return f"{len(entries)} counties"


def build_catalog_context(workspace: Workspace) -> dict[str, object]:
    """Return the Data Catalog context.

    Shared by the workspace hub page and the map view's Data Catalog panel
    so the two surfaces can't drift apart.
    """
    categories = DataSourceCategory.objects.prefetch_related("sources").order_by(
        "sort_order"
    )
    for category in categories:
        for source in category.sources.all():
            url_name = _IMPORT_TYPE_URL_NAMES.get(source.import_type)
            source.import_url = (
                f"{reverse(url_name)}?workspace={workspace.pk}" if url_name else ""
            )
            source.is_manual_upload = source.import_type in _MANUAL_UPLOAD_TYPES
            source.action_label = "Upload" if source.is_manual_upload else "Import"

    return {
        "workspace": workspace,
        "catalog_categories": categories,
        "imported_types": list(
            DataImportRun.objects.filter(workspace=workspace, status="completed")
            .values_list("import_type", flat=True)
            .distinct()
        ),
    }


class WorkspaceSettingsForm(forms.ModelForm):
    """Workspace-level settings editable from the hub page (not admin)."""

    class Meta:
        model = Workspace
        fields = ["tile_server_backend"]
        widgets = {
            "tile_server_backend": forms.Select(attrs={"class": "form-select"}),
        }


@user_passes_test(lambda u: u.is_authenticated)
def workspace_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the workspace detail hub page."""
    workspace = get_object_or_404(Workspace, pk=pk)

    county_q = Q()
    for entry in workspace.county_fips_list:
        county_q |= Q(
            state_fips=entry["state"],
            county_fips=entry["county"],
        )

    context: dict[str, object] = {
        "counties": County.objects.filter(county_q),
        "region_summary": _build_region_summary(workspace),
        "analysis_modules": build_analysis_modules(workspace),
        "recent_runs": AnalysisRun.objects.filter(workspace=workspace).order_by(
            "-created_at"
        )[:5],
        "settings_form": WorkspaceSettingsForm(instance=workspace),
        **build_catalog_context(workspace),
    }

    return render(request, "workspace/workspace_detail.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def workspace_settings_update(request: HttpRequest, pk: int) -> HttpResponse:
    """Save workspace-level settings (e.g. tile server backend) from the hub page."""
    workspace = get_object_or_404(Workspace, pk=pk)
    form = WorkspaceSettingsForm(request.POST, instance=workspace)
    if form.is_valid():
        form.save()
    return redirect("workspace:workspace_detail", pk=pk)
