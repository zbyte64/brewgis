"""Great Expectations integration for Brew GIS data quality.

Public API
----------
- ``get_gx_context()`` — Return the file-backed Data Context.
- ``validate_base_canvas(schema, table)`` — Validate a base canvas table.
- ``validate_census_acs(schema, table)`` — Validate a Census ACS staging table.
- ``validate_lehd(schema, table)`` — Validate a LEHD LODES staging table.
- ``validate_poi(schema, table)`` — Validate a POI staging table.
- ``validate_nlcd(schema, table)`` — Validate an NLCD staging table.
- ``validate_dbt_table(schema, table, suite_name)`` — Validate a dbt model output.
- ``validate_synthetic_parcels(schema, table)`` — Validate synthetic parcel table.
- ``run_checkpoint(checkpoint_name)`` — Run a named checkpoint.
- ``run_all_checkpoints(severity=None)`` — Run every configured checkpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings

try:
    import great_expectations as gx

    GX_AVAILABLE = True
except ImportError:
    GX_AVAILABLE = False


__all__ = [
    "GX_AVAILABLE",
    "get_gx_context",
    "run_all_checkpoints",
    "run_checkpoint",
    "validate_base_canvas",
    "validate_census_acs",
    "validate_dbt_table",
    "validate_lehd",
    "validate_nlcd",
    "validate_poi",
    "validate_synthetic_parcels",
]

logger = logging.getLogger(__name__)


def get_gx_context() -> gx.DataContext:
    """Return the file-backed Great Expectations Data Context.

    Uses the directory configured in settings.GX_PROJECT_DIR
    (default ``brewgis/gx/``).
    """
    if not GX_AVAILABLE:
        msg = "great_expectations is not installed"
        raise RuntimeError(msg)
    project_dir = getattr(settings, "GX_PROJECT_DIR", None)
    if project_dir is None:
        project_dir = Path(__file__).resolve().parent
    return gx.data_context.FileDataContext(str(project_dir))


# ── Checkpoint runner ──────────────────────────────────────────────


def run_checkpoint(checkpoint_name: str) -> dict[str, Any]:
    """Run a named checkpoint and return its result summary.

    Returns a dict with keys:
        success (bool)
        run_name (str)
        failures (list of failed expectation descriptions)
        results_url (str | None)
    """
    context = get_gx_context()
    checkpoint = context.checkpoints[checkpoint_name]
    run_result = checkpoint.run()
    return _summarise_run(run_result, checkpoint_name)


def run_all_checkpoints(severity: str | None = None) -> list[dict[str, Any]]:
    """Run every checkpoint registered in the Data Context.

    Args:
        severity: If ``"critical"``, only run checkpoints tagged critical.
                  If ``"warning"``, run all checkpoints.

    Returns a list of result summaries (one per checkpoint).
    """
    context = get_gx_context()
    summaries: list[dict[str, Any]] = []
    for name in context.list_checkpoints():
        if severity == "critical" and not _is_critical_checkpoint(context, name):
            continue
        summaries.append(run_checkpoint(name))
    return summaries


# ── Convenience validators ─────────────────────────────────────────


def _run_suite(context: gx.DataContext, suite_name: str, schema: str, table: str) -> dict[str, Any]:
    """Run a named Expectation Suite against ``schema.table``.

    Returns the checkpoint-style summary dict.
    """
    batch_request = _build_batch_request(context, schema, table)
    if batch_request is None:
        return {
            "success": False,
            "run_name": suite_name,
            "failures": [f"Datasource or data_asset not found for {schema}.{table}"],
            "results_url": None,
        }
    validator = context.get_validator(
        batch_request=batch_request,
        expectation_suite_name=suite_name,
    )
    validator.head()  # force column metadata load
    results = validator.validate()
    return _summarise_suite_results(suite_name, results)


def validate_base_canvas(schema: str = "public", table: str = "base_canvas") -> dict[str, Any]:
    """Validate a base canvas table against the ``base_canvas`` expectation suite."""
    context = get_gx_context()
    return _run_suite(context, "base_canvas", schema, table)


def validate_census_acs(schema: str = "public", table: str = "census_acs") -> dict[str, Any]:
    """Validate a Census ACS staging table."""
    context = get_gx_context()
    return _run_suite(context, "census_acs_staging", schema, table)


def validate_lehd(schema: str = "public", table: str = "lehd_lodes") -> dict[str, Any]:
    """Validate a LEHD LODES staging table."""
    context = get_gx_context()
    return _run_suite(context, "lehd_staging", schema, table)


def validate_poi(schema: str = "public", table: str = "poi") -> dict[str, Any]:
    """Validate a POI staging table."""
    context = get_gx_context()
    return _run_suite(context, "poi_staging", schema, table)


def validate_nlcd(schema: str = "public", table: str = "nlcd") -> dict[str, Any]:
    """Validate an NLCD staging table."""
    context = get_gx_context()
    return _run_suite(context, "nlcd_staging", schema, table)


def validate_dbt_table(schema: str, table: str, suite_name: str) -> dict[str, Any]:
    """Validate a dbt model output table.

    ``suite_name`` should be one of:
    ``dbt_core_end_state``, ``dbt_env_constraint``, ``dbt_trip_generation``,
    ``dbt_trip_distribution``, ``dbt_mode_choice``, ``dbt_scenario_summary``,
    or ``built_form_export``, ``spatial_allocation``, ``column_stitching``.
    """
    context = get_gx_context()
    return _run_suite(context, suite_name, schema, table)


def validate_synthetic_parcels(schema: str = "public", table: str = "synthetic_parcels") -> dict[str, Any]:
    """Validate a synthetic parcels table."""
    context = get_gx_context()
    return _run_suite(context, "synthetic_parcels", schema, table)


# ── Internal helpers ───────────────────────────────────────────────


def _build_batch_request(
    context: gx.DataContext,
    schema: str,
    table: str,
) -> Any:
    """Build a batch request for ``schema.table``.

    Returns ``None`` if the datasource or data asset cannot be found.
    """
    datasource_name = "brewgis_postgis"
    try:
        datasource = context.data_sources.get(datasource_name)
    except KeyError:
        logger.warning("Datasource '%s' not found", datasource_name)
        return None

    # GX Core uses table_name as the data_asset name within the datasource.
    data_asset_name = f"{schema}.{table}"
    try:
        data_asset = datasource.get_asset(data_asset_name)
    except KeyError:
        logger.warning(
            "Data asset '%s' not found in datasource '%s'",
            data_asset_name,
            datasource_name,
        )
        return None

    return data_asset.build_batch_request()


def _summarise_run(result: Any, checkpoint_name: str) -> dict[str, Any]:
    """Convert a CheckpointResult to a plain dict summary."""
    success = result.success
    failures: list[str] = []
    for run_result in result.run_results.values():
        for suite_result in run_result.get("validation_results", []):
            for expectation in suite_result.get("results", []):
                if not expectation.get("success", True):
                    ec = expectation.get("expectation_config", {})
                    failures.append(
                        f"{ec.get('expectation_type', 'unknown')}: "
                        f"{ec.get('kwargs', {})}"
                    )
    return {
        "success": success,
        "checkpoint": checkpoint_name,
        "failures": failures,
        "results_url": None,
    }


def _summarise_suite_results(suite_name: str, results: Any) -> dict[str, Any]:
    """Convert a Validator.validate() result to a summary dict."""
    success = results.success
    failures: list[str] = []
    for expectation in getattr(results, "results", []):
        if not expectation.get("success", True):
            ec = expectation.get("expectation_config", {})
            failures.append(
                f"{ec.get('expectation_type', 'unknown')}: "
                f"{ec.get('kwargs', {})}"
            )
    return {
        "success": success,
        "run_name": suite_name,
        "failures": failures,
        "results_url": None,
    }


def _is_critical_checkpoint(context: gx.DataContext, name: str) -> bool:
    """Check whether a checkpoint is tagged as severity=critical."""
    try:
        cp = context.checkpoints.get(name)
        meta = getattr(cp, "meta", None) or {}
        return meta.get("severity") == "critical"
    except Exception:  # noqa: BLE001
        return False
