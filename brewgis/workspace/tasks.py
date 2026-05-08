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
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
from brewgis.workspace.services.census_fetcher import fetch_acs_block_groups
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_data
from brewgis.workspace.services.poi_fetcher import fetch_pois
from brewgis.workspace.services.spatial_allocator import allocate_attributes
from brewgis.workspace.services.stitcher import impute_area_proportional
from brewgis.workspace.services.preflight import check_analysis_prerequisites
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
#  Analysis module tasks
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="run_env_constraint",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_env_constraint(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Environmental Constraint dbt model.

    Args:
        workspace_id: Workspace primary key (used for layer registration).
        vars_: dbt variables dict. Expected keys:
            - source_schema: Schema containing source tables.
            - parcel_table: Table name for parcels.
            - constraints: JSON list of constraint layer definitions.
            - target_schema: Schema for output.
            - scenario_id: Unique scenario identifier.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running env_constraint for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["env_constraint"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "env_constraint completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"env_constraint_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "env_constraint failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_core_module",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_core_module(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Core / Scenario Builder dbt models (end_state + increment).

    Before running dbt, ensures the built_forms export table exists by
    calling :func:`export_building_types`.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, end_state_table,
        increment_table, layer_schema.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running core module for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    # Pre-dispatch validation (defense in depth)
    parcel_table = resolved_vars.get("parcel_table", "")
    source_schema = resolved_vars.get("source_schema", "public")
    built_form_table = resolved_vars.get("built_form_table", "built_forms")
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
            "end_state_table": None,
            "increment_table": None,
            "layer_schema": None,
        }

    # Ensure the built_forms export table exists before running dbt
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
            "end_state_table": None,
            "increment_table": None,
            "layer_schema": None,
        }

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["core_end_state", "core_increment"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "Core module completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "end_state_table": f"end_state_{scenario_id}",
            "increment_table": f"increment_{scenario_id}",
            "layer_schema": target_schema,
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "Core module failed for workspace %s: %s",
        workspace_id,
        error_msg,
    )
    return {
        "success": False,
        "results": [],
        "error": error_msg,
        "end_state_table": None,
        "increment_table": None,
        "layer_schema": None,
    }


# ────────────────────────────────────────────────────────────
#  Water & Energy Demand tasks
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="run_water_demand",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_water_demand(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Water Demand dbt model.

    Computes residential and non-residential water demand from the
    end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running water_demand for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["water_demand"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "water_demand completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"water_demand_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "water_demand failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_energy_demand",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_energy_demand(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Energy Demand dbt model.

    Computes residential and non-residential energy demand (electricity + gas)
    from the end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running energy_demand for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["energy_demand"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "energy_demand completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"energy_demand_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "energy_demand failed for workspace %s: %s",
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
#  Land Consumption, Fiscal & Agriculture tasks
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="run_land_consumption",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_land_consumption(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Land Consumption dbt model (L1 + L2).

    Computes land use transitions and impervious surface estimates
    from the end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running land_consumption for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["land_consumption"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "land_consumption completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"land_consumption_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "land_consumption failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_fiscal",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_fiscal(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Fiscal dbt models (F1–F4).

    Computes property tax, sales tax, service costs, and net fiscal impact
    from the end-state allocation table.  Uses ref() ordering so dbt
    runs F1→F2→F3→F4 in dependency order.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running fiscal for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=[
            "fiscal_property_tax",
            "fiscal_sales_tax",
            "fiscal_service_costs",
            "fiscal_net_impact",
        ],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "fiscal completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"fiscal_property_tax_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "fiscal failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_agriculture",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_agriculture(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Agriculture dbt model.

    Computes crop yield, market value, production costs, and resource
    use from the end-state allocation table.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running agriculture for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["agriculture"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "agriculture completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"agriculture_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "agriculture failed for workspace %s: %s",
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
#  Transportation module tasks (T1–T4)
# ────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="run_trip_generation",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_trip_generation(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Trip Generation dbt model (T1).

    Computes daily trip generation per parcel from ITE rates.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running trip_generation for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["trip_generation"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "trip_generation completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"trip_generation_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "trip_generation failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_trip_distribution",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_trip_distribution(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Trip Distribution dbt Python model (T2).

    Computes parcel-to-parcel trip distribution using a gravity model.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running trip_distribution for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["trip_distribution"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "trip_distribution completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"trip_distribution_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "trip_distribution failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_mode_choice",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_mode_choice(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the Mode Choice dbt Python model (T3).

    Computes mode split (auto/transit/walk/bike) using multinomial logit.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running mode_choice for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["mode_choice"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "mode_choice completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"mode_choice_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "mode_choice failed for workspace %s: %s",
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


@shared_task(
    bind=True,
    name="run_vmt",
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=60,
)
def run_vmt(
    self,
    workspace_id: int,
    vars_: dict | None = None,
) -> dict:
    """Run the VMT dbt model (T4).

    Computes vehicle miles traveled from mode choice and trip distribution.

    Args:
        workspace_id: Workspace primary key.
        vars_: dbt variables dict.

    Returns:
        Dict with keys: success, results, error, layer_schema, layer_table.
    """
    resolved_vars = vars_ or {}
    logger.info(
        "Running vmt for workspace %s with vars: %s",
        workspace_id,
        resolved_vars,
    )

    runner = DbtRunnerWrapper()
    dbt_result = runner.run(
        select=["vmt"],
        vars_=resolved_vars,
        full_refresh=True,
    )

    if dbt_result.success:
        target_schema = resolved_vars.get("target_schema", "public")
        scenario_id = resolved_vars.get("scenario_id", "default")
        logger.info(
            "vmt completed for workspace %s (scenario %s)",
            workspace_id,
            scenario_id,
        )
        return {
            "success": True,
            "results": dbt_result.results,
            "error": None,
            "layer_schema": target_schema,
            "layer_table": f"vmt_{scenario_id}",
        }

    error_msg = dbt_result.error or "Unknown dbt error"
    logger.error(
        "vmt failed for workspace %s: %s",
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

    # Module → result table name templates (mirrors pipeline.MODULE_RESULT_TABLES)
    table_templates: list[str] = []
    if module == "env_constraint":
        table_templates = [f"env_constraint_{scenario_id}"]
    elif module == "core":
        table_templates = [
            f"end_state_{scenario_id}",
            f"increment_{scenario_id}",
        ]
    elif module == "water_demand":
        table_templates = [f"water_demand_{scenario_id}"]
    elif module == "energy_demand":
        table_templates = [f"energy_demand_{scenario_id}"]

    elif module == "land_consumption":
        table_templates = [
            f"land_consumption_{scenario_id}",
            f"impervious_surface_{scenario_id}",
        ]
    elif module == "fiscal":
        table_templates = [
            f"fiscal_property_tax_{scenario_id}",
            f"fiscal_sales_tax_{scenario_id}",
            f"fiscal_service_costs_{scenario_id}",
            f"fiscal_net_impact_{scenario_id}",
        ]
    elif module == "agriculture":
        table_templates = [f"agriculture_{scenario_id}"]
    for table_name in table_templates:
        register_result_layer(
            workspace_id=workspace_id,
            schema=layer_schema,
            table=table_name,
            name=f"{module.replace('_', ' ').title()} — {scenario_id}",
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
    from brewgis.workspace.analysis.pipeline import (  # noqa: PLC0415, I001
        _get_vars_for_module,
        MODULE_TASKS,
    )

    module = remaining[0]
    module_vars = _get_vars_for_module(
        module,
        {**base_vars, "completed_modules": list(completed_modules)},
    )

    run.status = "running"
    run.started_at = __import__("django").utils.timezone.now()
    run.save(update_fields=["status", "started_at"])

    scenario_id = base_vars.get("scenario_id", "default")

    task_func = MODULE_TASKS.get(module)
    if task_func is None:
        run.status = "failed"
        run.error_log = f"Unknown module: {module}"
        run.completed_at = __import__("django").utils.timezone.now()
        run.save(update_fields=["status", "error_log", "completed_at"])
        return

    _plain_logger.info(
        "Dispatching next module '%s' for AnalysisRun #%s",
        module,
        run.pk,
    )

    task_func.apply_async(
        kwargs={
            "workspace_id": run.workspace_id,
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
