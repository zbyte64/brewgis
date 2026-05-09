from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import County
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import DataSourceCategory
from brewgis.workspace.models import Workspace

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
        "name": "Environmental Constraint",
        "description": "Overlay environmental constraints on base parcels",
        "inputs": ["Base parcels", "Constraint layers"],
        "outputs": ["Environmental constraint overlay"],
        "prereq_status": "",
    },
    {
        "name": "Core Allocation",
        "description": "End-state allocation plus increment analysis",
        "inputs": ["Scenario parameters", "Base allocation"],
        "outputs": ["End-state allocation", "Increment from base"],
        "prereq_status": "",
    },
    {
        "name": "Water Demand",
        "description": "Residential and non-residential water demand in L/yr",
        "inputs": ["Allocated parcels", "Density factors"],
        "outputs": ["Water demand (L/yr)"],
        "prereq_status": "",
    },
    {
        "name": "Energy Demand",
        "description": "Residential and non-residential energy demand in kWh/yr",
        "inputs": ["Allocated parcels", "Density factors"],
        "outputs": ["Energy demand (kWh/yr)"],
        "prereq_status": "",
    },
]


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
        "workspace": workspace,
        "counties": County.objects.filter(county_q),
        "region_summary": _build_region_summary(workspace),
        "catalog_categories": DataSourceCategory.objects.prefetch_related("sources").order_by("sort_order"),
        "imported_types": list(
            DataImportRun.objects.filter(workspace=workspace, status="completed")
            .values_list("import_type", flat=True)
            .distinct()
        ),
        "analysis_modules": ANALYSIS_MODULES,
        "recent_runs": AnalysisRun.objects.filter(workspace=workspace).order_by(
            "-created_at"
        )[:5],
    }

    return render(request, "workspace/workspace_detail.html", context)
