"""Soda Core integration for Brew GIS data quality.

Replaces Great Expectations with Soda Core v4 for fully-local,
schema-aware data quality validation.

Public API (matching the old ``brewgis.gx`` surface)::

    run_scan(contract_name, schema, table)
    validate_base_canvas(schema, table)
    validate_census_acs(schema, table)
    validate_lehd(schema, table)
    validate_poi(schema, table)
    validate_nlcd(schema, table)
    validate_synthetic_parcels(schema, table)
    validate_spatial_allocation(schema, table)
    validate_column_stitching(schema, table)
    validate_built_form_export(schema, table)

All return ``dict[str, Any]`` with keys:

    success (bool)         — True if every check passed
    checkpoint (str)       — contract name
    failures (list[str])   — human-readable descriptions of failed checks
    results_url (str|None) — always None (local-only)
    severity (str|None)    — always None (all checks are warnings by default)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

__all__ = [
    "run_scan",
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


# ── Paths ───────────────────────────────────────────────────────────


def _soda_dir() -> Path:
    """Return the Soda project directory (settable via ``SODA_PROJECT_DIR``)."""
    return Path(getattr(settings, "SODA_PROJECT_DIR", settings.APPS_DIR / "soda"))


# Default table names for contracts that use ``__TABLE__`` placeholders.
# Maps ``contract_name`` → ``schema.table`` so that management-command runs
# (which do not supply schema/table) resolve correctly.
_DEFAULT_TABLE: dict[str, str] = {
    "base_canvas": "public.base_canvas",
    "census_acs": "public.census_acs",
    "lehd": "public.lehd_lodes",
    "poi": "public.poi",
    "nlcd": "public.nlcd",
    "synthetic_parcels": "public.synthetic_parcels",
    "spatial_allocation": "public.spatial_allocation",
    "column_stitching": "public.column_stitching",
    "built_form_export": "public.built_forms",
    "dbt_module_run": "public.dbt_module_run",
}
# ── Scan runner ─────────────────────────────────────────────────────

SODA_AVAILABLE: bool = True
try:
    from soda.scan import Scan
except ImportError:
    Scan = None  # type: ignore[assignment,misc]
    SODA_AVAILABLE = False
    logger.warning("soda-core not installed — data quality validation is disabled")


def run_scan(
    contract_name: str,
    schema: str | None = None,
    table: str | None = None,
) -> dict[str, Any]:
    """Run a Soda scan for *contract_name* against ``schema.table``.

    Returns a dict matching the old ``brewgis.gx.run_checkpoint`` contract.

    When *schema* and *table* are both provided the scan targets that
    dynamic dataset.  When either is ``None`` the scan runs against the
    dataset name baked into the contract YAML (useful for dbt-module runs
    where the table name is known statically).
    """
    if not SODA_AVAILABLE:
        logger.warning("soda-core unavailable; skipping scan for '%s'", contract_name)
        return _empty_result(contract_name)

    soda_dir = _soda_dir()
    config_path = soda_dir / "configuration.yml"
    contract_path = soda_dir / "contracts" / f"{contract_name}.yml"

    if not contract_path.exists():
        logger.warning("Contract '%s' not found at %s", contract_name, contract_path)
        return _empty_result(contract_name)

    # Read the contract YAML and inject the target dataset
    yaml_content = contract_path.read_text(encoding="utf-8")
    if schema is not None and table is not None:
        qualified = f"{schema}.{table}"
    else:
        qualified = _DEFAULT_TABLE.get(contract_name, f"public.{contract_name}")
    yaml_content = yaml_content.replace("__TABLE__", qualified)

    scan = Scan()  # type: ignore[union-attr]
    scan.add_configuration_yaml_file(str(config_path))
    scan.add_sodacl_yaml_str(yaml_content)
    scan.set_is_local(True)
    scan.execute()

    return _summarise_scan(scan, contract_name)


# ── Convenience validators ─────────────────────────────────────────


def validate_base_canvas(
    schema: str = "public", table: str = "base_canvas"
) -> dict[str, Any]:
    """Validate a base canvas table."""
    return run_scan("base_canvas", schema=schema, table=table)


def validate_census_acs(
    schema: str = "public", table: str = "census_acs"
) -> dict[str, Any]:
    """Validate a Census ACS staging table."""
    return run_scan("census_acs", schema=schema, table=table)


def validate_lehd(schema: str = "public", table: str = "lehd_lodes") -> dict[str, Any]:
    """Validate a LEHD LODES staging table."""
    return run_scan("lehd", schema=schema, table=table)


def validate_poi(schema: str = "public", table: str = "poi") -> dict[str, Any]:
    """Validate a POI staging table."""
    return run_scan("poi", schema=schema, table=table)


def validate_nlcd(schema: str = "public", table: str = "nlcd") -> dict[str, Any]:
    """Validate an NLCD staging table."""
    return run_scan("nlcd", schema=schema, table=table)


def validate_dbt_table(
    schema: str, table: str, _suite_name: str = ""
) -> dict[str, Any]:
    """Validate a dbt model output table.

    *suite_name* is accepted for API compatibility with the old
    ``brewgis.gx.validate_dbt_table`` but not used — all dbt module
    checks live under the generic ``dbt_module_run`` contract.
    """
    return run_scan("dbt_module_run", schema=schema, table=table)


def validate_synthetic_parcels(
    schema: str = "public", table: str = "synthetic_parcels"
) -> dict[str, Any]:
    """Validate a synthetic parcels table."""
    return run_scan("synthetic_parcels", schema=schema, table=table)


def validate_spatial_allocation(
    schema: str = "public", table: str = "spatial_allocation"
) -> dict[str, Any]:
    """Validate a spatial allocation output table."""
    return run_scan("spatial_allocation", schema=schema, table=table)


def validate_column_stitching(
    schema: str = "public", table: str = "column_stitching"
) -> dict[str, Any]:
    """Validate a column stitching / imputation output table."""
    return run_scan("column_stitching", schema=schema, table=table)


def validate_built_form_export(
    schema: str = "public", table: str = "built_forms"
) -> dict[str, Any]:
    """Validate a built form export table."""
    return run_scan("built_form_export", schema=schema, table=table)


# ── Internal helpers ───────────────────────────────────────────────


def _empty_result(contract_name: str) -> dict[str, Any]:
    """Return a no-op pass result (matches old GX fallback behaviour)."""
    return {
        "success": True,
        "failures": [],
        "results_url": None,
        "severity": None,
        "checkpoint": contract_name,
    }


def _summarise_scan(scan: Any, contract_name: str) -> dict[str, Any]:
    """Convert a Soda ``Scan`` result to the dict shape callers expect."""
    has_failures = scan.has_check_fails()

    failures = [
        f"{check.name}: {check.outcome_reason or 'failed'}"
        for check in scan.get_checks_fail()
    ]

    return {
        "success": not has_failures,
        "checkpoint": contract_name,
        "failures": failures,
        "results_url": None,
        "severity": None,
    }
