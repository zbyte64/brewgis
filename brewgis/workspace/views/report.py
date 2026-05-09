"""Views for generating, listing, and downloading reports."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import user_passes_test
from django.http import FileResponse
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_safe

from brewgis.workspace.models import ScenarioReport
from brewgis.workspace.models import Workspace
from brewgis.workspace.tasks import generate_report_task


@user_passes_test(lambda u: u.is_authenticated)
def report_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """List all reports for a workspace."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    reports = ScenarioReport.objects.filter(workspace=workspace)
    context: dict[str, object] = {
        "workspace": workspace,
        "reports": reports,
        "report_types": ScenarioReport.ReportType.choices,
    }
    return render(request, "workspace/report/list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
def report_detail(request: HttpRequest, workspace_pk: int, report_pk: int) -> HttpResponse:
    """View a single report. Returns the file if completed, otherwise renders detail."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    report = get_object_or_404(ScenarioReport, pk=report_pk, workspace=workspace)

    if report.report_file:
        return FileResponse(
            report.report_file.open("rb"),
            content_type="application/pdf",
            filename=report.report_file.name,
        )

    context: dict[str, object] = {
        "workspace": workspace,
        "report": report,
    }
    return render(request, "workspace/report/detail.html", context)


@require_safe
@user_passes_test(lambda u: u.is_authenticated)
def report_status(request: HttpRequest, workspace_pk: int, report_pk: int) -> HttpResponse:
    """htmx-polled status partial for a report."""
    report = get_object_or_404(ScenarioReport, pk=report_pk, workspace_id=workspace_pk)
    return render(
        request,
        "workspace/report/partials/_report_status.html",
        {"report": report, "workspace": report.workspace},
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def generate_scenario_report(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Generate a scenario comparison report."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    name = request.POST.get("name", "").strip() or f"Scenario Report - {workspace.name}"

    report = ScenarioReport.objects.create(
        workspace=workspace,
        name=name,
        report_type=ScenarioReport.ReportType.SCENARIO_COMPARISON,
        status=ScenarioReport.ReportStatus.PENDING,
        created_by=request.user if request.user.is_authenticated else None,
    )

    generate_report_task.delay(report.pk)

    return JsonResponse({"pk": report.pk, "status": report.status})


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def generate_paint_report(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Generate a paint tracking report."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    scenario_id = request.POST.get("scenario_id", "").strip()
    name = request.POST.get("name", "").strip() or f"Paint Report - {workspace.name}"

    report = ScenarioReport.objects.create(
        workspace=workspace,
        scenario_id=scenario_id or None,
        name=name,
        report_type=ScenarioReport.ReportType.PAINT_TRACKING,
        status=ScenarioReport.ReportStatus.PENDING,
        created_by=request.user if request.user.is_authenticated else None,
    )

    generate_report_task.delay(report.pk)

    return JsonResponse({"pk": report.pk, "status": report.status})


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def generate_map_report(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Generate a map export report."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        body = {}

    options = {
        "map_image": body.get("map_image", ""),
        "title": body.get("title", ""),
        "dpi": body.get("dpi", 300),
        "include_legend": body.get("include_legend", True),
    }
    name = body.get("name", "").strip() or f"Map Export - {workspace.name}"

    report = ScenarioReport.objects.create(
        workspace=workspace,
        name=name,
        report_type=ScenarioReport.ReportType.MAP_EXPORT,
        status=ScenarioReport.ReportStatus.PENDING,
        created_by=request.user if request.user.is_authenticated else None,
        export_options=options,
    )

    generate_report_task.delay(report.pk)

    return JsonResponse({"pk": report.pk, "status": report.status})


@require_safe
@user_passes_test(lambda u: u.is_authenticated)
def report_list_partial(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """htmx partial for filtered report list."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    reports = ScenarioReport.objects.filter(workspace=workspace)

    report_type = request.GET.get("type", "").strip()
    if report_type:
        reports = reports.filter(report_type=report_type)

    return render(
        request,
        "workspace/report/partials/_report_list.html",
        {
            "workspace": workspace,
            "reports": reports,
        },
    )
