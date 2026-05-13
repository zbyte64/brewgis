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
- ``validate_spatial_allocation(schema, table)`` — Validate a spatial allocation table.
- ``validate_column_stitching(schema, table)`` — Validate a column stitching table.
- ``validate_built_form_export(schema, table)`` — Validate a built form export table.
- ``run_checkpoint(checkpoint_name, schema=None, table=None)`` — Run a named checkpoint, optionally against a specific table.
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
    "run_checkpoint",
    "validate_base_canvas",
    "validate_built_form_export",
    "validate_census_acs",
    "validate_column_stitching",
    "validate_dbt_table",
    "validate_lehd",
    "validate_nlcd",
    "validate_poi",
    "validate_spatial_allocation",
    "validate_synthetic_parcels",
]

logger = logging.getLogger(__name__)


def get_gx_context() -> "gx.DataContext":  # type: ignore[name-defined]
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
    gx_config = project_dir / "great_expectations.yml"
    if not gx_config.exists():
        msg = (
            f"Great Expectations config not found at {gx_config}. "
            "Run `great_expectations init` or check GX_PROJECT_DIR setting."
        )
        raise FileNotFoundError(msg)
    return gx.data_context.FileDataContext(str(project_dir))  # type: ignore[arg-type]


# ── Checkpoint runner ──────────────────────────────────────────────


def run_checkpoint(
    checkpoint_name: str, schema: str | None = None, table: str | None = None
) -> dict[str, Any]:
    """Run a named checkpoint and return its result summary.

    If *both* *schema* and *table* are provided the checkpoint is run
    against that specific table rather than its configured default.

    Returns a dict with keys:
        success (bool)
        run_name (str)
        failures (list of failed expectation descriptions)
        results_url (str | None)
        severity (str | None)
    """
    context = get_gx_context()
    checkpoint = context.checkpoints[checkpoint_name]
    meta = getattr(checkpoint, "meta", None) or {}
    severity = meta.get("severity")
    if schema is not None and table is not None:
        batch_request = _build_batch_request(context, schema, table)
        run_result = checkpoint.run(batch_request=batch_request)
    else:
        run_result = checkpoint.run()
    return _summarise_run(run_result, checkpoint_name, severity=severity)


# ── Convenience validators ─────────────────────────────────────────


def validate_base_canvas(
    schema: str = "public", table: str = "base_canvas"
) -> dict[str, Any]:
    """Validate a base canvas table against the ``base_canvas`` expectation suite."""
    return run_checkpoint("base_canvas_etl", schema=schema, table=table)


def validate_census_acs(
    schema: str = "public", table: str = "census_acs"
) -> dict[str, Any]:
    """Validate a Census ACS staging table."""
    return run_checkpoint("census_ingest", schema=schema, table=table)


def validate_lehd(schema: str = "public", table: str = "lehd_lodes") -> dict[str, Any]:
    """Validate a LEHD LODES staging table."""
    return run_checkpoint("lehd_ingest", schema=schema, table=table)


def validate_poi(schema: str = "public", table: str = "poi") -> dict[str, Any]:
    """Validate a POI staging table."""
    return run_checkpoint("poi_ingest", schema=schema, table=table)


def validate_nlcd(schema: str = "public", table: str = "nlcd") -> dict[str, Any]:
    """Validate an NLCD staging table."""
    return run_checkpoint("nlcd_ingest", schema=schema, table=table)


def validate_dbt_table(schema: str, table: str, suite_name: str) -> dict[str, Any]:
    """Validate a dbt model output table.

    ``suite_name`` should be one of:
    ``dbt_core_end_state``, ``dbt_env_constraint``, ``dbt_trip_generation``,
    ``dbt_trip_distribution``, ``dbt_mode_choice``, ``dbt_scenario_summary``.
    """
    return run_checkpoint("dbt_module_run")


def validate_synthetic_parcels(
    schema: str = "public", table: str = "synthetic_parcels"
) -> dict[str, Any]:
    """Validate a synthetic parcels table."""
    return run_checkpoint("synthetic_parcels", schema=schema, table=table)


def validate_spatial_allocation(
    schema: str = "public", table: str = "spatial_allocation"
) -> dict[str, Any]:
    """Validate a spatial allocation output table."""
    return run_checkpoint("spatial_allocation", schema=schema, table=table)


def validate_column_stitching(
    schema: str = "public", table: str = "column_stitching"
) -> dict[str, Any]:
    """Validate a column stitching / imputation output table."""
    return run_checkpoint("column_stitching", schema=schema, table=table)


def validate_built_form_export(
    schema: str = "public", table: str = "built_forms"
) -> dict[str, Any]:
    """Validate a built form export table."""
    return run_checkpoint("built_form_export", schema=schema, table=table)


# ── Internal helpers ───────────────────────────────────────────────


def _build_batch_request(
    context: "gx.DataContext",  # type: ignore[name-defined]
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


def _summarise_run(
    result: Any, checkpoint_name: str, severity: str | None = None
) -> dict[str, Any]:
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
        "severity": severity,
    }
