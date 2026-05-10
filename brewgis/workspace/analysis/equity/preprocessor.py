"""ACS Equity Data preprocessor — joins ACS equity variables to parcels.

ROADMAP_2 Phase 1c: Fills displacement_risk and housing_cost_burden
prerequisites by matching parcels to block-group ACS equity data.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# Fallback equity data used when ACS source is unavailable.
# Based on national ACS 2019 5-year estimates.
FALLBACK_EQUITY: dict[str, float | int] = {
    "median_income": 50000,
    "rent_burden_pct": 32.0,
    "pct_minority": 40.0,
    "pct_college_educated": 30.0,
}

DEFAULT_PARQUET_COLUMNS_FILE = "acs_equity_defaults"


def run_acs_equity_preprocessor(vars_: dict) -> dict:
    """Preprocessor for ACS equity data.

    Attempts to join equity variables from an ACS block-group table.
    Falls back to uniform defaults if no ACS table is available.
    """
    target_schema = vars_.get("target_schema", "public")
    base_canvas_table = vars_.get("base_canvas_table", "base_canvas")
    source_schema = vars_.get("source_schema", target_schema)
    acs_table = vars_.get("acs_equity_table", None)

    if not acs_table:
        logger.warning(
            "No acs_equity_table var set. Using uniform default equity values. "
            "Set acs_equity_table to a table with columns: geoid, median_income, "
            "rent_burden_pct, pct_minority, pct_college_educated"
        )
        _apply_uniform_equity_defaults(target_schema, base_canvas_table, vars_)
        return {"success": True, "method": "uniform_defaults"}

    try:
        with connection.cursor() as cursor:
            # Check if ACS table exists
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                [source_schema, acs_table],
            )
            table_exists = cursor.fetchone()[0]

            if not table_exists:
                logger.warning(
                    "ACS equity table %s.%s not found. Using uniform defaults.",
                    source_schema, acs_table,
                )
                _apply_uniform_equity_defaults(target_schema, base_canvas_table, vars_)
                return {"success": True, "method": "uniform_defaults"}

            # Run the join: update base_canvas with ACS equity values
            # Using parcel-to-block-group spatial join
            cursor.execute(
                f"""
                UPDATE {target_schema}.{base_canvas_table} AS bc
                SET
                    median_income = COALESCE(bc.median_income, acs.median_income, {FALLBACK_EQUITY['median_income']}),
                    rent_burden_pct = COALESCE(bc.rent_burden_pct, acs.rent_burden_pct, {FALLBACK_EQUITY['rent_burden_pct']}),
                    pct_minority = COALESCE(bc.pct_minority, acs.pct_minority, {FALLBACK_EQUITY['pct_minority']}),
                    pct_college_educated = COALESCE(bc.pct_college_educated, acs.pct_college_educated, {FALLBACK_EQUITY['pct_college_educated']})
                FROM {source_schema}.{acs_table} AS acs
                WHERE ST_Intersects(bc.geometry, acs.geom)
                """
            )
            updated = cursor.rowcount
            logger.info("Updated %s parcels with ACS equity data from %s.%s", updated, source_schema, acs_table)

            # Fill remaining nulls with defaults
            _apply_uniform_equity_defaults(target_schema, base_canvas_table, vars_)

            return {"success": True, "method": "acs_join", "updated": updated}

    except Exception as exc:
        logger.warning("ACS equity join failed: %s. Using uniform defaults.", exc)
        _apply_uniform_equity_defaults(target_schema, base_canvas_table, vars_)
        return {"success": True, "method": "uniform_defaults_fallback"}


def _apply_uniform_equity_defaults(target_schema: str, base_canvas_table: str, vars_: dict) -> None:
    """Fill NULL equity columns with uniform default values."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {target_schema}.{base_canvas_table}
            SET
                median_income = COALESCE(median_income, {FALLBACK_EQUITY['median_income']}),
                rent_burden_pct = COALESCE(rent_burden_pct, {FALLBACK_EQUITY['rent_burden_pct']}),
                pct_minority = COALESCE(pct_minority, {FALLBACK_EQUITY['pct_minority']}),
                pct_college_educated = COALESCE(pct_college_educated, {FALLBACK_EQUITY['pct_college_educated']})
            WHERE median_income IS NULL
               OR rent_burden_pct IS NULL
               OR pct_minority IS NULL
               OR pct_college_educated IS NULL
            """
        )
        filled = cursor.rowcount
        logger.info("Filled %s parcels with uniform ACS equity defaults", filled)
