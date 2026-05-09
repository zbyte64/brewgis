# ruff: noqa: ANN001, ARG001
"""Celery tasks for analysis pipeline execution."""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone
from sqlalchemy import create_engine

from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
from brewgis.workspace.services.census_fetcher import fetch_acs_block_groups
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_data
from brewgis.workspace.services.poi_fetcher import fetch_pois
from brewgis.workspace.services.preflight import check_analysis_prerequisites
from brewgis.workspace.services.spatial_allocator import allocate_attributes
from brewgis.workspace.services.stitcher import impute_area_proportional
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
def export_building_types_task(
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
    try:
        count = export_building_types(schema=schema, table=table)
        logger.info(
            "Built form export complete: %d rows in %s.%s",
            count,
            schema,
            table,
        )
        return {"success": True, "count": count, "error": None}
    except Exception as e:
        logger.exception("Built form export failed")
        return {"success": False, "count": 0, "error": str(e)}


# ────────────────────────────────────────────────────────────
#  Analysis module tasks (consolidated)
# ────────────────────────────────────────────────────────────

MODULE_DBT_SELECT_MAP = {
    "env_constraint": ["env_constraint"],
    "core": ["core_end_state", "core_increment"],
    "water_demand": ["water_demand"],
    "energy_demand": ["energy_demand"],
    "land_consumption": ["land_consumption"],
    "fiscal": [
        "fiscal_property_tax",
        "fiscal_sales_tax",
        "fiscal_service_costs",
        "fiscal_net_impact",
    ],
    "agriculture": ["agriculture"],
    "trip_generation": ["trip_generation"],
    "trip_distribution": ["trip_distribution"],
    "mode_choice": ["mode_choice"],
    "vmt": ["vmt"],
}


@shared_task(
    bind=True,
    name="run_dbt_module",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_dbt_module(
    self,
    workspace_id: int,
    module: str,
    vars_: dict | None = None,
) -> dict:
    """Run a dbt analysis module.

    Single parameterized task for all analysis modules.  The ``module``
    argument selects the set of dbt models to run.

    Args:
        workspace_id: Workspace primary key (used for layer registration).
        module: Module name (e.g. ``water_demand``, ``fiscal``, ``core``).
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running module '%s' for workspace %s with vars: %s",
        module,
        workspace_id,
        resolved_vars,
    )

    # ── Core module: preflight + export ──────────────────────
    if module == "core":
        source_schema = resolved_vars.get("source_schema", "public")
        built_form_table = resolved_vars.get("built_form_table", "built_forms")
        parcel_table = resolved_vars.get("parcel_table", "")
        base_canvas_table = resolved_vars.get("base_canvas_table")
        preflight_errors = check_analysis_prerequisites(
            schema=source_schema,
            parcel_table=parcel_table,
            built_form_table=built_form_table,
            base_canvas_table=base_canvas_table,
        )
        if preflight_errors:
            error_msg = "; ".join(e.message for e in preflight_errors)
            logger.error(
                "Preflight validation failed for workspace %s: %s",
                workspace_id,
                error_msg,
            )
            return {
                "success": False,
                "results": [],
                "error": error_msg,
                "layer_schema": None,
            }

        try:
            export_building_types(schema=source_schema, table=built_form_table)
        except Exception:
            logger.exception(
                "Built form export failed before core module run (workspace %s)",
                workspace_id,
            )
            return {
                "success": False,
                "results": [],
                "error": "Failed to export built form data from Django models",
                "layer_schema": None,
            }

    # ── Run dbt ──────────────────────────────────────────────
    select = MODULE_DBT_SELECT_MAP.get(module)
    if not select:
        return {
            "success": False,
            "results": [],
            "error": f"Unknown module: {module}",
            "layer_schema": None,
        }

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=select,
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "Module '%s' completed for workspace %s (scenario %s)",
            module,
            workspace_id,
            scenario_id,
        )
        # First table in the select list is the "primary" result table
        primary_table = select[0]
        table_name = f"{primary_table}_{scenario_id}"
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": table_name,
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "Module '%s' failed for workspace %s: %s",
        module,
        workspace_id,
        error_msg,
    )
    return {
        "success": False,
        "results": [],
        "error": error_msg,
        "layer_schema": None,
        "layer_table": None,
    }


# ────────────────────────────────────────────────────────────
#  Pipeline chain callback
# ────────────────────────────────────────────────────────────


@shared_task(
    name="handle_module_completed",
    max_retries=0,
)
def handle_module_completed(
    task_result: dict,
    run_id: int,
    workspace_id: int,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
    scenario_id: str,
) -> None:
    """Callback fired after each module task completes successfully.

    Receives the parent task's return value as ``task_result`` (the first
    positional argument from the Celery ``link``), plus keyword args
    from the :meth:`celery.s` signature in ``_dispatch_next``.

    If the module succeeded, result layers are registered and the next
    module is dispatched.  On failure, the AnalysisRun is marked as
    failed.
    """
    try:
        run = AnalysisRun.objects.get(pk=run_id)
    except AnalysisRun.DoesNotExist:
        _plain_logger.error(
            "handle_module_completed: AnalysisRun #%s not found",
            run_id,
        )
        return

    if not task_result.get("success"):
        run.status = "failed"
        run.error_log = task_result.get("error", "Module task returned failure")
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        _plain_logger.error(
            "AnalysisRun #%s: module %s failed: %s",
            run_id,
            completed_modules[-1] if completed_modules else "unknown",
            run.error_log,
        )
        return

    # Register result layers for the completed module
    module = completed_modules[-1] if completed_modules else "unknown"
    _register_module_results(workspace_id, module, task_result, scenario_id)

    # Dispatch the next module
    _dispatch_next_in_task(run, remaining, base_vars, completed_modules)


def _register_module_results(
    workspace_id: int,
    module: str,
    task_result: dict,
    scenario_id: str,
) -> None:
    """Register dbt result views as Layers (lightweight, no django import cycle)."""

    layer_schema = task_result.get("layer_schema")
    if not layer_schema:
        return

    label = get_module_label(module)
    for table_name in get_result_table_names(module, scenario_id):
        register_result_layer(
            workspace_id=workspace_id,
            schema=layer_schema,
            table=table_name,
            name=f"{label} — {scenario_id}",
            description=f"Analysis result for module '{module}' (scenario: {scenario_id})",
        )


def _dispatch_next_in_task(
    run: AnalysisRun,
    remaining: list[str],
    base_vars: dict[str, Any],
    completed_modules: list[str],
) -> None:
    """Dispatch the next module from within a Celery task context.

    Mirrors :func:`pipeline._dispatch_next` but operates on a fresh
    AnalysisRun instance loaded from the database (no stale object).
    """
    if not remaining:
        run.status = "completed"
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "completed_at"])
        _plain_logger.info("AnalysisRun #%s completed successfully", run.pk)
        return

    # Avoid circular import: tasks → pipeline → tasks
    from brewgis.workspace.analysis.module_registry import (  # noqa: PLC0415, I001
        get_vars_for_module,
    )

    module = remaining[0]
    module_vars = get_vars_for_module(
        module,
        {**base_vars, "completed_modules": list(completed_modules)},
    )

    run.status = "running"
    run.started_at = __import__("django").utils.timezone.now()
    run.save(update_fields=["status", "started_at"])

    scenario_id = base_vars.get("scenario_id", "default")

    _plain_logger.info(
        "Dispatching next module '%s' for AnalysisRun #%s",
        module,
        run.pk,
    )

    run_dbt_module.apply_async(
        kwargs={
            "workspace_id": run.workspace_id,
            "module": module,
            "vars_": module_vars,
        },
        link=handle_module_completed.s(
            run_id=run.pk,
            workspace_id=run.workspace_id,
            remaining=remaining[1:],
            base_vars=base_vars,
            completed_modules=[*completed_modules, module],
            scenario_id=scenario_id,
        ),
    )
# ────────────────────────────────────────────────────────────
#  Data import tasks (Census, LEHD, POI, Allocation, Stitching)
# ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_census_fetch(
    self,
    run_pk: int,
    state_fips: str,
    county_fips: str,
    schema: str,
) -> dict:
    """Fetch Census ACS demographics data and write to PostGIS."""

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

        gdf = fetch_acs_block_groups(state_fips, county_fips)

        if gdf.empty:
            msg = "Census fetch returned empty result."
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

        table_name = f"census_acs_{state_fips}_{county_fips}"

        # Write to PostGIS

        db_url = settings.DATABASES["default"]["NAME"]
        db_user = settings.DATABASES["default"]["USER"]
        db_pass = settings.DATABASES["default"]["PASSWORD"]
        db_host = settings.DATABASES["default"]["HOST"]
        db_port = settings.DATABASES["default"]["PORT"]
        engine = create_engine(
            f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_url}"
        )
        gdf.to_postgis(table_name, engine, schema=schema, if_exists="replace", index=False)
        engine.dispose()

        # Register as Layer

        layer, created = Layer.objects.get_or_create(
            key=f"census_acs_{state_fips}_{county_fips}",
            workspace=run.workspace,
            defaults={
                "name": f"ACS Demographics ({state_fips}-{county_fips})",
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
            "layer_key": f"census_acs_{state_fips}_{county_fips}",
            "layer_id": layer.pk,
            "row_count": len(gdf),
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        return {"success": True, "count": len(gdf)}

    except DataImportRun.DoesNotExist:
        return {"success": False, "error": f"DataImportRun {run_pk} not found"}
    except Exception as exc:
        try:
            run = DataImportRun.objects.get(pk=run_pk)
            run.status = "failed"
            run.error_log = str(exc)
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
        except DataImportRun.DoesNotExist:
            pass
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_lehd_fetch(
    self,
    run_pk: int,
    state_fips: str,
    county_fips: str,
    schema: str,
) -> dict:
    """Fetch LEHD employment data and write to PostGIS."""

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])


        gdf = fetch_lehd_block_data(state_fips, county_fips)

        if gdf.empty:
            msg = "LEHD fetch returned empty result."
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

        table_name = f"lehd_{state_fips}_{county_fips}"


        db_url = settings.DATABASES["default"]["NAME"]
        db_user = settings.DATABASES["default"]["USER"]
        db_pass = settings.DATABASES["default"]["PASSWORD"]
        db_host = settings.DATABASES["default"]["HOST"]
        db_port = settings.DATABASES["default"]["PORT"]
        engine = create_engine(
            f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_url}"
        )
        gdf.to_postgis(table_name, engine, schema=schema, if_exists="replace", index=False)
        engine.dispose()


        layer, created = Layer.objects.get_or_create(
            key=f"lehd_{state_fips}_{county_fips}",
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
            "layer_key": f"lehd_{state_fips}_{county_fips}",
            "layer_id": layer.pk,
            "row_count": len(gdf),
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        return {"success": True, "count": len(gdf)}

    except DataImportRun.DoesNotExist:
        return {"success": False, "error": f"DataImportRun {run_pk} not found"}
    except Exception as exc:
        try:
            run = DataImportRun.objects.get(pk=run_pk)
            run.status = "failed"
            run.error_log = str(exc)
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
        except DataImportRun.DoesNotExist:
            pass
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_poi_fetch(
    self,
    run_pk: int,
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    categories: list[str] | None,
    schema: str,
) -> dict:
    """Fetch POIs from OpenStreetMap Overpass and write to PostGIS."""

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])


        gdf = fetch_pois(min_lng, min_lat, max_lng, max_lat, categories)

        if gdf.empty:
            msg = "POI fetch returned empty result."
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

        suffix = uuid4().hex[:8]
        table_name = f"poi_{suffix}"
        layer_key = f"poi_{suffix}"


        db_url = settings.DATABASES["default"]["NAME"]
        db_user = settings.DATABASES["default"]["USER"]
        db_pass = settings.DATABASES["default"]["PASSWORD"]
        db_host = settings.DATABASES["default"]["HOST"]
        db_port = settings.DATABASES["default"]["PORT"]
        engine = create_engine(
            f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_url}"
        )
        gdf.to_postgis(table_name, engine, schema=schema, if_exists="replace", index=False)
        engine.dispose()


        cat_label = ",".join(categories) if categories else "all"
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
            "row_count": len(gdf),
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        return {"success": True, "count": len(gdf)}

    except DataImportRun.DoesNotExist:
        return {"success": False, "error": f"DataImportRun {run_pk} not found"}
    except Exception as exc:
        try:
            run = DataImportRun.objects.get(pk=run_pk)
            run.status = "failed"
            run.error_log = str(exc)
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
        except DataImportRun.DoesNotExist:
            pass
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_spatial_allocation(
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

    try:
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

        run.status = "completed"
        run.result = result
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        return {"success": True, **result}

    except DataImportRun.DoesNotExist:
        return {"success": False, "error": f"DataImportRun {run_pk} not found"}
    except Exception as exc:
        try:
            run = DataImportRun.objects.get(pk=run_pk)
            run.status = "failed"
            run.error_log = str(exc)
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
        except DataImportRun.DoesNotExist:
            pass
        return {"success": False, "error": str(exc)}


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_column_stitching(
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

    try:
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

        elif strategy == "area_proportional":
            if not source_table or not source_column:
                msg = "Source table and column required for area_proportional strategy."
                run.status = "failed"
                run.error_log = msg
                run.completed_at = timezone.now()
                run.save(update_fields=["status", "error_log", "completed_at"])
                return {"success": False, "error": msg}

            result = impute_area_proportional(
                schema, table, target_column,
                schema, source_table, source_column,
            )

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

        return {"success": True, **result}

    except DataImportRun.DoesNotExist:
        return {"success": False, "error": f"DataImportRun {run_pk} not found"}
    except Exception as exc:
        try:
            run = DataImportRun.objects.get(pk=run_pk)
            run.status = "failed"
            run.error_log = str(exc)
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
        except DataImportRun.DoesNotExist:
            pass
        return {"success": False, "error": str(exc)}
