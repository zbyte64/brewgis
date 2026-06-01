# ruff: noqa: ANN001, ARG001
"""Celery tasks for analysis pipeline execution."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone

from brewgis.soda import validate_column_stitching
from brewgis.soda import validate_spatial_allocation
from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.dlt_pipelines import run_census_pipeline
from brewgis.workspace.dlt_pipelines import run_lehd_pipeline
from brewgis.workspace.dlt_pipelines import run_poi_pipeline
from brewgis.workspace.dlt_pipelines import run_raster_pipeline
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
from brewgis.workspace.services.spatial_allocator import allocate_attributes
from brewgis.workspace.services.stitcher import impute_built_form_default
from brewgis.workspace.services.stitcher import impute_constant
from brewgis.workspace.symbology.auto import auto_generate_symbology

logger = get_task_logger(__name__)
_plain_logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
#  Data export (prerequisite for core module)
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="export_building_types",
    autoretry_for=(RuntimeError,),
    max_retries=2,
    default_retry_delay=30,
)
def export_building_types_task(  # type: ignore[no-untyped-def]
    self,
    schema: str = "public",
    table: str = "built_forms",
    **kwargs: Any,
) -> dict:
    """Export BuildingType Django records to a flat PostGIS table for dbt.

    Creates ``{schema}.{table}`` with columns matching the
    ``core_end_state`` dbt model's expectations.

    Returns:
        Dict with keys: success, count, error.
    """
    count = export_building_types(schema=schema, table=table)
    logger.info(
        "Built form export complete: %d rows in %s.%s",
        count,
        schema,
        table,
    )

    return {"success": True, "count": count, "error": None}


# ────────────────────────────────────────────────────────────
#  Data import tasks (Census, LEHD, POI, Allocation, Stitching)
# ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_census_fetch(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    state_fips: str,
    county_fips: str,
    schema: str,
    year: int = 2022,
) -> dict:
    """Fetch Census ACS demographics data via dlt and register as Layer.

    The dlt pipeline writes raw data to the staging table
    ``{schema}.acs_raw``.  No geopandas re-read is performed — the
    dlt-loaded table IS the source of truth for downstream processing.
    """

    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    dlt_result = run_census_pipeline(state_fips, county_fips, year, schema)

    table_name = dlt_result["table_name"]
    row_count = dlt_result["row_count"]
    layer_key = f"census_acs_{year}_{state_fips}_{county_fips}"

    layer, created = Layer.objects.get_or_create(
        key=layer_key,
        workspace=run.workspace,
        defaults={
            "name": f"ACS Demographics ({year}) ({state_fips}-{county_fips})",
            "db_table": table_name,
            "layer_source": "Census ACS",
            "geometry_type": "circle",
        },
    )

    if created:
        auto_generate_symbology(layer)
    run.status = "completed"
    run.result = {
        "table_name": table_name,
        "layer_key": layer_key,
        "layer_id": layer.pk,
        "row_count": row_count,
        "validation": dlt_result.get("validation"),
    }
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])

    return {"count": row_count}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_lehd_fetch(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    state_fips: str,
    county_fips: str,
    schema: str,
    year: int = 2022,
) -> dict:
    """Fetch LEHD employment data via dlt and register as Layer.
    The dlt pipeline writes raw data to the staging table
    ``{schema}.lodes_raw``. No geopandas re-read is performed.
    """
    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    dlt_result = run_lehd_pipeline(state_fips, county_fips, year, schema=schema)

    table_name = dlt_result["table_name"]
    row_count = dlt_result["row_count"]
    layer_key = f"lehd_{state_fips}_{county_fips}"

    layer, created = Layer.objects.get_or_create(
        key=layer_key,
        workspace=run.workspace,
        defaults={
            "name": f"LEHD Employment ({state_fips}-{county_fips})",
            "db_table": table_name,
            "layer_source": "Census LEHD",
            "geometry_type": "circle",
        },
    )

    if created:
        auto_generate_symbology(layer)
    run.status = "completed"
    run.result = {
        "table_name": table_name,
        "layer_key": layer_key,
        "layer_id": layer.pk,
        "row_count": row_count,
        "validation": dlt_result.get("validation"),
    }
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])

    return {"count": row_count}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_poi_fetch(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None,
    schema: str,
) -> dict:
    """Fetch POIs from OpenStreetMap Overpass via dlt and register as Layer.

    The dlt pipeline writes raw data to the staging table
    ``{schema}.poi_raw``. No geopandas re-read is performed.
    """

    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    dlt_result = run_poi_pipeline(
        min_lng, min_lat, max_lng, max_lat, categories, schema=schema
    )

    table_name = dlt_result["table_name"]
    row_count = dlt_result["row_count"]
    cat_label = ",".join(categories) if categories else "all"
    layer_key = f"poi_{min_lng}_{min_lat}_{max_lng}_{max_lat}_{cat_label}"

    layer, created = Layer.objects.get_or_create(
        key=layer_key,
        workspace=run.workspace,
        defaults={
            "name": f"POI ({cat_label})",
            "db_table": table_name,
            "layer_source": "OpenStreetMap",
            "geometry_type": "circle",
        },
    )

    if created:
        auto_generate_symbology(layer)
    run.status = "completed"
    run.result = {
        "table_name": table_name,
        "layer_key": layer_key,
        "layer_id": layer.pk,
        "row_count": row_count,
        "validation": dlt_result.get("validation"),
    }
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])

    return {"count": row_count}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_raster_fetch(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    file_path: str,
    schema: str,
) -> dict:
    """Extract raster metadata and band statistics from GeoTIFF via dlt.

    The dlt pipeline reads the file and writes to staging tables
    ``{schema}.raster_metadata`` and ``{schema}.raster_bands``.
    A Layer is registered pointing to the metadata table.
    """

    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    dlt_result = run_raster_pipeline(file_path, schema)

    metadata_table = dlt_result["metadata_table"]
    bands_table = dlt_result["bands_table"]
    row_count = dlt_result["row_count"]
    fname = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    layer_key = f"raster_{fname}"

    layer, created = Layer.objects.get_or_create(
        key=layer_key,
        workspace=run.workspace,
        defaults={
            "name": f"Raster ({fname})",
            "db_table": metadata_table,
            "layer_source": "Raster",
            "geometry_type": "raster",
        },
    )

    if created:
        auto_generate_symbology(layer)
    run.status = "completed"
    run.result = {
        "metadata_table": metadata_table,
        "bands_table": bands_table,
        "layer_key": layer_key,
        "layer_id": layer.pk,
        "row_count": row_count,
        "validation": dlt_result.get("validation"),
    }
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])

    return {"count": row_count}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_spatial_allocation(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    columns: list[str],
    column_prefix: str = "",
    source_geom_col: str = "geom",
    target_geom_col: str = "geom",
) -> dict:
    """Run spatial allocation between source and target layers."""

    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    result = allocate_attributes(
        source_schema=source_schema,
        source_table=source_table,
        target_schema=target_schema,
        target_table=target_table,
        columns=columns,
        target_column_prefix=column_prefix,
        source_geom_col=source_geom_col,
        target_geom_col=target_geom_col,
    )

    # Validate allocation output with Soda
    validation = validate_spatial_allocation(
        schema=target_schema,
        table=target_table,
    )
    if not validation["success"]:
        logger.warning(
            "Spatial allocation validation failed for %s.%s: %s",
            target_schema,
            target_table,
            "; ".join(validation.get("failures", [])),
        )

    result["validation"] = validation

    run.status = "completed"
    run.result = result
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])
    return result


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_column_stitching(  # type: ignore[no-untyped-def]
    self,
    run_pk: int,
    schema: str,
    table: str,
    target_column: str,
    strategy: str,
    default_value: float | None = None,
    source_table: str | None = None,
    source_column: str | None = None,
) -> dict:
    """Run column stitching / imputation on a table."""

    run = DataImportRun.objects.get(pk=run_pk)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    if strategy == "constant":
        if default_value is None:
            msg = "Default value required for constant strategy."
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

        result = impute_constant(schema, table, target_column, default_value)

    elif strategy == "built_form_default":
        result = impute_built_form_default(schema, table, target_column)

    else:
        msg = f"Unknown strategy: {strategy}"
        run.status = "failed"
        run.error_log = msg
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        return {"success": False, "error": msg}

    run.status = "completed"
    run.result = result
    run.completed_at = timezone.now()
    run.save(update_fields=["status", "result", "completed_at"])

    # Default validation after stitching — full context needed here
    gx_result = validate_column_stitching(schema=schema, table=table)
    if gx_result["success"]:
        logger.info("GX validation passed for column_stitching")
    else:
        msg = "; ".join(gx_result["failures"][:5])
        raise RuntimeError(
            f"GX validation failed for column_stitching ({schema}.{table}): {msg}"
        )
    return result


# ────────────────────────────────────────────────────────────
#  Report generation tasks (Phase 7b, 7f)
# ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report_task(self, report_pk: int) -> dict:  # type: ignore[no-untyped-def]
    """Generate a report (scenario comparison, paint tracking, or map export) as PDF."""
    from pathlib import Path

    from django.template.loader import render_to_string
    from django.utils import timezone

    from brewgis.workspace.models import PaintEvent
    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import ScenarioReport

    report = ScenarioReport.objects.get(pk=report_pk)
    report.status = ScenarioReport.ReportStatus.RUNNING
    report.save(update_fields=["status"])

    from weasyprint import HTML

    context = {
        "report_name": report.name,
        "generated_at": timezone.now(),
    }

    if report.report_type == ScenarioReport.ReportType.SCENARIO_COMPARISON:
        template = "workspace/report/scenario_report_pdf.html"
        scenarios = Scenario.objects.filter(workspace=report.workspace)
        metrics_list = []
        for scenario in scenarios:
            metrics_dict = _build_report_scenario_metrics(scenario)
            metrics_list.append(
                {
                    "scenario": scenario,
                    "metrics": metrics_dict,
                }
            )
        context["scenarios"] = scenarios
        context["metrics"] = metrics_list

    elif report.report_type == ScenarioReport.ReportType.PAINT_TRACKING:
        template = "workspace/report/paint_report_pdf.html"
        paint_scenario: Scenario | None = report.scenario
        context["scenario_name"] = paint_scenario.name if paint_scenario else "\u2014"
        paint_events = (
            PaintEvent.objects.filter(scenario=paint_scenario)
            .select_related("painted_by")
            .order_by("-painted_at")[:500]
        )
        context["paint_events"] = paint_events

    elif report.report_type == ScenarioReport.ReportType.MAP_EXPORT:
        template = "workspace/report/map_export_pdf.html"
        opts = report.export_options or {}
        context["title"] = opts.get("title", report.name)
        context["map_image"] = opts.get("map_image", "")
        context["include_legend"] = opts.get("include_legend", True)

    else:
        raise ValueError(f"Unknown report type: {report.report_type}")

    html_str = render_to_string(template, context)
    pdf_file = HTML(string=html_str).write_pdf()

    reports_dir = Path(settings.MEDIA_ROOT) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{report.report_type}_{report.pk}_{timezone.now():%Y%m%d_%H%M%S}.pdf"
    filepath = reports_dir / filename
    with open(filepath, "wb") as f:
        f.write(pdf_file)

    report.report_file.name = f"reports/{filename}"
    report.status = ScenarioReport.ReportStatus.COMPLETED
    report.completed_at = timezone.now()
    report.save(update_fields=["report_file", "status", "completed_at"])

    return {"success": True, "report_pk": report_pk, "file": filename}


def _build_report_scenario_metrics(scenario: Any) -> dict[str, Any]:
    """Build aggregate metrics for a scenario for the report.
    Simplified version of _build_comparison_metrics in scenarios.py.
    Queries the scenario canvas view for key aggregate values.
    """
    from django.db import connection

    metrics: dict[str, float | None] = {
        "total_population": None,
        "total_households": None,
        "total_du": None,
        "total_employment": None,
        "total_vmt": None,
        "total_water": None,
        "total_energy": None,
        "total_land_consumed_acres": None,
    }

    view_name = scenario.canvas_view_name

    with connection.cursor() as cursor:
        parts = view_name.split(".")
        table_name = parts[1] if len(parts) > 1 else view_name
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            [scenario.schema_name, table_name],
        )
        exists = cursor.fetchone()[0]
        if not exists:
            return metrics

        cursor.execute(
            "SELECT "
            'SUM("total_population"), SUM("total_households"), SUM("total_du"), '
            'SUM("total_employment"), SUM("vmt"), SUM("water"), SUM("energy"), '
            'SUM("acres") '
            f"FROM {view_name}"
        )
        row = cursor.fetchone()
        if row:
            keys = list(metrics.keys())
            for i, key in enumerate(keys):
                if i < len(row) and row[i] is not None:
                    metrics[key] = float(row[i])

    # VMT Fee metrics (Phase 2b) — if vmt_fee table exists
    vmt_fee_table = f"vmt_fee_{scenario.slug}"
    target_schema = scenario.workspace.db_schema
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            )
            """,
            [target_schema, vmt_fee_table],
        )
        if cursor.fetchone()[0]:
            cursor.execute(
                f"SELECT COALESCE(SUM(fee_revenue_total), 0), "
                f"COALESCE(SUM(revenue_forgone), 0), "
                f"COALESCE(SUM(vmt_exempt), 0) "
                f'FROM "{target_schema}"."{vmt_fee_table}"'
            )
            row = cursor.fetchone()
            metrics["vmt_fee_revenue"] = round(row[0], 2)
            metrics["vmt_fee_revenue_forgone"] = round(row[1], 2)
            metrics["vmt_fee_vmt_exempt"] = round(row[2], 2)
            metrics["vmt_fee_rate"] = scenario.vars.get(
                "vmt_fee_rate_dollars_per_vmt", 295.0
            )

    return metrics
