# ruff: noqa: ANN001, ARG001
"""Celery tasks for analysis pipeline execution."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.utils import timezone

from brewgis.gx import validate_census_acs
from brewgis.gx import validate_dbt_table
from brewgis.gx import validate_lehd
from brewgis.gx import validate_poi
from brewgis.workspace.analysis.data_export import export_building_types
from brewgis.workspace.analysis.dbt_runner import DbtRunnerWrapper
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.module_registry import get_module_label
from brewgis.workspace.analysis.module_registry import get_result_table_names
from brewgis.workspace.dlt_pipelines import run_census_pipeline
from brewgis.workspace.dlt_pipelines import run_lehd_pipeline
from brewgis.workspace.dlt_pipelines import run_poi_pipeline
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
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
#
# Celery bridge tasks for analysis pipeline execution. Each task
# runs the work directly (Celery provides async execution). When
# Dagster is available, these tasks also attempt to submit a run
# to the Dagster daemon for unified observability.
# ────────────────────────────────────────────────────────────

MODULE_DBT_SELECT_MAP = {
    "env_constraint": ["env_constraint"],
    "core": ["core_end_state", "core_increment"],
    "water_demand": ["water_demand"],
    "displacement_risk": ["displacement_risk"],
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
    "food_access": ["food_access"],
    "housing_cost_burden": ["housing_cost_burden"],
    "sprawl_index": ["sprawl_index"],
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

        # Optional post-dbt GX validation (warning severity — don't block pipeline)
        suite_name = f"dbt_{module}"
        validation_result = validate_dbt_table(
            schema=target_schema,
            table=table_name,
            suite_name=suite_name,
        )
        if validation_result["success"]:
            logger.info("GX validation passed for module '%s'", module)
        else:
            logger.warning(
                "GX validation warning for module '%s' (table %s.%s): %s",
                module,
                target_schema,
                table_name,
                "; ".join(validation_result["failures"][:5]),
            )
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
#  Preprocessor tasks — run before dbt for transport modules
# ────────────────────────────────────────────────────────────

# Module → preprocessor function: maps module names to their preprocessor
# callback. Each preprocessor receives (vars_: dict) and returns dict with
# keys: success, error.
PREPROCESSOR_MAP: dict[str, Any] = {}


def _run_internal_capture_preprocessor(vars_: dict) -> dict:
    """Preprocessor for internal_capture: creates capture input table."""
    from brewgis.workspace.analysis.transport.preprocessors import (  # noqa: PLC0415
        DistanceMatrixPreprocessor,
    )

    scenario_id = vars_.get("scenario_id", "default")
    target_schema = vars_.get("target_schema", "public")
    end_state_table = vars_.get("end_state_table", "end_state_{scenario_id}")

    preprocessor = DistanceMatrixPreprocessor()
    return preprocessor.compute_distance_matrix(
        schema=target_schema,
        end_state_table=end_state_table,
        edge_table="network_edges",
        scenario_id=scenario_id,
    )


PREPROCESSOR_MAP["internal_capture"] = _run_internal_capture_preprocessor


def _run_food_access_preprocessor(vars_: dict) -> dict:
    """Preprocessor for food_access: runs OSM POI-based mRFEI computation."""
    from brewgis.workspace.analysis.food_access.preprocessor import (
        FoodAccessPreprocessor,
    )

    preprocessor = FoodAccessPreprocessor()
    scenario_id = vars_.get("scenario_id", "default")
    target_schema = vars_.get("target_schema", "public")
    workspace_id = vars_.get("workspace_id")
    end_state_table = vars_.get("end_state_table", "end_state_{scenario_id}")
    return preprocessor.compute_mrfei(
        schema=target_schema,
        end_state_table=end_state_table,
        scenario_id=scenario_id,
        workspace_id=workspace_id,
    )


PREPROCESSOR_MAP["food_access"] = _run_food_access_preprocessor
from brewgis.workspace.analysis.equity.preprocessor import run_acs_equity_preprocessor

PREPROCESSOR_MAP["acs_equity"] = run_acs_equity_preprocessor


@shared_task(
    bind=True,
    name="run_preprocessor_and_dbt",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_preprocessor_and_dbt(
    self,
    workspace_id: int,
    module: str,
    vars_: dict | None = None,
) -> dict:
    """Run a preprocessor, then execute the corresponding dbt module.

    This task wraps the standard `run_dbt_module` with a preprocessor
    step that creates input tables before dbt runs.

    Args:
        workspace_id: Workspace primary key.
        module: Module name.
        vars_: dbt variables dict.

    Returns:
        Same shape as run_dbt_module.
    """
    resolved_vars = vars_ or {}
    resolved_vars.setdefault("workspace_id", workspace_id)
    logger.info(
        "Running preprocessor + dbt for module '%s' (workspace %s)",
        module,
        workspace_id,
    )

    # Run preprocessor if one is registered
    preprocessor_fn = PREPROCESSOR_MAP.get(module)
    if preprocessor_fn:
        preproc_result = preprocessor_fn(resolved_vars)
        if not preproc_result.get("success"):
            error_msg = preproc_result.get(
                "error", f"Preprocessor for '{module}' failed"
            )
            logger.error(
                "Preprocessor failed for module '%s': %s",
                module,
                error_msg,
            )
            return {
                "success": False,
                "results": [],
                "error": error_msg,
                "layer_schema": None,
                "layer_table": None,
            }
        logger.info(
            "Preprocessor for '%s' succeeded: %s",
            module,
            preproc_result,
        )

    # Delegate to the standard dbt runner
    return run_dbt_module(
        self,
        workspace_id=workspace_id,
        module=module,
        vars_=resolved_vars,
    )


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
    from brewgis.workspace.analysis.module_registry import (  # noqa: PLC0415
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
    year: int = 2022,
) -> dict:
    """Fetch Census ACS demographics data via dlt and register as Layer.

    The dlt pipeline writes raw data to the staging table
    ``{schema}.acs_raw``.  No geopandas re-read is performed — the
    dlt-loaded table IS the source of truth for downstream processing.
    """

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

        dlt_result = run_census_pipeline(state_fips, county_fips, year, schema)
        if not dlt_result["success"]:
            msg = f"dlt extraction failed: {dlt_result['error']}"
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

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
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        # Optional GX validation on ingested data (warning severity)
        try:
            result = validate_census_acs(schema=schema, table=table_name)
            if not result["success"]:
                logger.warning(
                    "GX validation warning for census data (table %s.%s): %s",
                    schema,
                    table_name,
                    "; ".join(result["failures"][:5]),
                )
        except Exception:
            logger.warning("GX validation skipped for census data", exc_info=True)

        return {"success": True, "count": row_count}
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
    """Fetch LEHD employment data via dlt and register as Layer.

    The dlt pipeline writes raw data to the staging table
    ``{schema}.lodes_raw``. No geopandas re-read is performed.
    """

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

        dlt_result = run_lehd_pipeline(state_fips, county_fips, schema=schema)
        if not dlt_result["success"]:
            msg = f"dlt extraction failed: {dlt_result['error']}"
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

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
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        # Optional GX validation on ingested data (warning severity)
        try:
            result = validate_lehd(schema=schema, table=table_name)
            if not result["success"]:
                logger.warning(
                    "GX validation warning for LEHD data (table %s.%s): %s",
                    schema,
                    table_name,
                    "; ".join(result["failures"][:5]),
                )
        except Exception:
            logger.warning("GX validation skipped for LEHD data", exc_info=True)

        return {"success": True, "count": row_count}

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
    """Fetch POIs from OpenStreetMap Overpass via dlt and register as Layer.

    The dlt pipeline writes raw data to the staging table
    ``{schema}.poi_raw``. No geopandas re-read is performed.
    """

    try:
        run = DataImportRun.objects.get(pk=run_pk)
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

        dlt_result = run_poi_pipeline(
            min_lng, min_lat, max_lng, max_lat, categories, schema=schema
        )
        if not dlt_result["success"]:
            msg = f"dlt extraction failed: {dlt_result['error']}"
            run.status = "failed"
            run.error_log = msg
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "error_log", "completed_at"])
            return {"success": False, "error": msg}

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
        }
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "result", "completed_at"])

        # Optional GX validation on ingested data (warning severity)
        try:
            result = validate_poi(schema=schema, table=table_name)
            if not result["success"]:
                logger.warning(
                    "GX validation warning for POI data (table %s.%s): %s",
                    schema,
                    table_name,
                    "; ".join(result["failures"][:5]),
                )
        except Exception:
            logger.warning("GX validation skipped for POI data", exc_info=True)

        return {"success": True, "count": row_count}
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
                schema,
                table,
                target_column,
                schema,
                source_table,
                source_column,
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


# ────────────────────────────────────────────────────────────
#  Report generation tasks (Phase 7b, 7f)
# ────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report_task(self, report_pk: int) -> dict:
    """Generate a report (scenario comparison, paint tracking, or map export) as PDF."""
    from pathlib import Path

    from django.conf import settings
    from django.template.loader import render_to_string
    from django.utils import timezone

    from brewgis.workspace.models import PaintEvent
    from brewgis.workspace.models import Scenario
    from brewgis.workspace.models import ScenarioReport

    report = ScenarioReport.objects.get(pk=report_pk)
    report.status = ScenarioReport.ReportStatus.RUNNING
    report.save(update_fields=["status"])

    try:
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
            scenario = report.scenario
            context["scenario_name"] = scenario.name if scenario else "\u2014"
            paint_events = (
                PaintEvent.objects.filter(scenario=scenario)
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
        filename = (
            f"{report.report_type}_{report.pk}_{timezone.now():%Y%m%d_%H%M%S}.pdf"
        )
        filepath = reports_dir / filename
        with open(filepath, "wb") as f:
            f.write(pdf_file)

        report.report_file.name = f"reports/{filename}"
        report.status = ScenarioReport.ReportStatus.COMPLETED
        report.completed_at = timezone.now()
        report.save(update_fields=["report_file", "status", "completed_at"])

        return {"success": True, "report_pk": report_pk, "file": filename}

    except Exception as exc:
        report.status = ScenarioReport.ReportStatus.FAILED
        report.error_log = str(exc)
        report.completed_at = timezone.now()
        report.save(update_fields=["status", "error_log", "completed_at"])
        return {"success": False, "report_pk": report_pk, "error": str(exc)}


def _build_report_scenario_metrics(scenario) -> dict:
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

    try:
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
    except Exception:
        pass

    # VMT Fee metrics (Phase 2b) — if vmt_fee table exists
    try:
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
    except Exception:
        pass

    return metrics
