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
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

# Import soda_core first to trigger its __init__.py plugin discovery before
# any soda_postgres module is loaded. This avoids the warning from
# load_plugins() trying to import PostgresDataSourceImpl via entry point
# while soda_postgres is partially initialized.
from soda_core.contracts import verify_contract_locally
from soda_postgres.common.data_sources.postgres_data_source import (
    PostgresDataSourceImpl,
)
from soda_postgres.common.data_sources.postgres_data_source_connection import (
    PostgresDataSource,
)

logger = logging.getLogger(__name__)

__all__ = [
    "run_scan",
    "validate_acs_block_group",
    "validate_base_canvas",
    "validate_built_form_export",
    "validate_census_acs",
    "validate_column_stitching",
    "validate_dbt_table",
    "validate_land_use_classification",
    "validate_lehd",
    "validate_nlcd",
    "validate_poi",
    "validate_spatial_allocation",
    "validate_synthetic_parcels",
    "validate_wac_block",
]


# ── Paths ───────────────────────────────────────────────────────────


def _soda_dir() -> Path:
    """Return the Soda project directory (settable via ``SODA_PROJECT_DIR``)."""
    return Path(getattr(settings, "SODA_PROJECT_DIR", settings.APPS_DIR / "soda"))


# Default table names for contracts that use ``__DATASET__`` placeholders.
# Maps ``contract_name`` → ``datasource/schema/table`` so that management-command
# runs (which do not supply schema/table) resolve to a valid dataset path
# including the registered datasource name.
_DEFAULT_TABLE: dict[str, str] = {
    "acs_block_group": "brewgis_postgis/census/acs_block_group",
    "base_canvas": "brewgis_postgis/public/base_canvas",
    "census_acs": "brewgis_postgis/public/census_acs",
    "lehd": "brewgis_postgis/public/lehd_lodes",
    "poi": "brewgis_postgis/public/poi",
    "nlcd": "brewgis_postgis/public/nlcd",
    "synthetic_parcels": "brewgis_postgis/public/synthetic_parcels",
    "spatial_allocation": "brewgis_postgis/public/spatial_allocation",
    "column_stitching": "brewgis_postgis/public/column_stitching",
    "built_form_export": "brewgis_postgis/public/built_forms",
    "dbt_module_run": "brewgis_postgis/public/dbt_module_run",
    "wac_block": "brewgis_postgis/lehd/wac_block",
}
# ── Scan runner ─────────────────────────────────────────────────────


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
    # Build DATABASE_URL from Django settings.
    db_conf = settings.DATABASES["default"]
    user = db_conf["USER"]
    password = db_conf["PASSWORD"]
    host = db_conf.get("HOST", "localhost")
    port = db_conf.get("PORT", "5432")
    name = db_conf["NAME"]
    database_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"

    parsed = urlparse(database_url)
    connection = {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
        "user": parsed.username or "",
        "password": parsed.password or "",
    }

    ds_model = PostgresDataSource(
        name="brewgis_postgis",
        connection=connection,
    )
    ds = PostgresDataSourceImpl(data_source_model=ds_model)

    soda_dir = _soda_dir()
    contract_path = soda_dir / "contracts" / f"{contract_name}.yml"

    if not contract_path.exists():
        logger.warning("Contract '%s' not found at %s", contract_name, contract_path)
        return _empty_result(contract_name)

    yaml_content = contract_path.read_text(encoding="utf-8")

    if schema is not None and table is not None:
        dataset_id = f"brewgis_postgis/{schema}/{table}"
    else:
        dataset_id = _DEFAULT_TABLE.get(contract_name, f"public/{contract_name}")

    yaml_content = yaml_content.replace("__DATASET__", dataset_id)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(yaml_content)

    result = verify_contract_locally(
        data_sources=[ds],
        contract_file_path=tmp.name,
    )
    Path(tmp.name).unlink(missing_ok=True)

    return _summarise_result(result, contract_name)


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


def validate_acs_block_group(
    schema: str = "census", table: str = "acs_block_group"
) -> dict[str, Any]:
    """Validate an ACS block group staging table."""
    return run_scan("acs_block_group", schema=schema, table=table)


def validate_wac_block(
    schema: str = "lehd", table: str = "wac_block"
) -> dict[str, Any]:
    """Validate a LEHD WAC block staging table."""
    return run_scan("wac_block", schema=schema, table=table)


def validate_land_use_classification(
    schema: str = "public", table: str = "base_canvas"
) -> dict[str, Any]:
    """Validate land use classification output."""
    return run_scan("land_use_classification", schema=schema, table=table)


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


def _summarise_result(result: Any, contract_name: str) -> dict[str, Any]:
    """Convert a ``verify_contract_locally`` result to the dict shape callers expect."""

    failures = [
        f"{c.check.name}: {c.check.definition}"
        for cvr in result.contract_verification_results
        for c in cvr.check_results
        if c.is_failed
    ]

    return {
        "success": result.is_passed,
        "checkpoint": contract_name,
        "failures": failures,
        "results_url": None,
        "severity": None,
    }
