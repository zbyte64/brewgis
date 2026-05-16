"""Column stitching / imputation tool — fills missing values in target columns.

Supports multiple imputation strategies:
- constant: Fill with a fixed default value.
- area_proportional: Fill from a source layer using area-weighted allocation.
- built_form_default: Fill from the nearest matching built form definition.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from django.db import connection

logger = logging.getLogger(__name__)

from brewgis.workspace.services.imputation_engine import ImputationEngine
from brewgis.workspace.services.imputation_engine import ImputationRule


def impute_constant(
    schema: str,
    table: str,
    column: str,
    value: float,
    target_geom_col: str = "geom",
) -> dict[str, Any]:
    """Fill all NULL values in a column with a constant default.

    Args:
        schema: Database schema name.
        table: Table name.
        column: Column name to fill.
        value: Default value to write.
        target_geom_col: Geometry column (unused for constant fill).

    Returns:
        Dict with keys: rows_updated, column.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{schema}"."{table}" SET "{column}" = %s WHERE "{column}" IS NULL',
            [value],
        )
        rows_updated = cursor.rowcount

    return {
        "rows_updated": rows_updated,
        "column": column,
    }


def impute_built_form_default(
    schema: str,
    table: str,
    column: str,
    built_form_table: str = "built_forms",
    join_column: str = "building_type_id",
    target_geom_col: str = "geom",
) -> dict[str, Any]:
    """Fill NULL values using defaults from a built form reference table.

    Assumes the target table has a join_column referencing a built form
    definition table that contains the target column.

    Args:
        schema: Database schema name.
        table: Target table.
        column: Column to fill.
        built_form_table: Reference table with default values.
        join_column: Column on target that joins to built_form_table.
        target_geom_col: Unused, for signature consistency.

    Returns:
        Dict with keys: rows_updated, column.
    """
    with connection.cursor() as cursor:
        # Check if the column exists in built_form_table
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            [schema, built_form_table, column],
        )
        if not cursor.fetchone():
            msg = f"Column '{column}' not found in '{schema}.{built_form_table}'."
            return {
                "rows_updated": 0,
                "error": msg,
                "column": column,
            }

        # Fill NULL values by joining with built form defaults
        cursor.execute(
            f'UPDATE "{schema}"."{table}" t '
            f'SET "{column}" = bf."{column}" '
            f'FROM "{schema}"."{built_form_table}" bf '
            f'WHERE t."{join_column}" = bf.id '
            f'AND t."{column}" IS NULL'
        )
        rows_updated = cursor.rowcount

    return {
        "rows_updated": rows_updated,
        "column": column,
    }


def stitch_dataframe(
    df: pd.DataFrame,
    rules: list[ImputationRule],
) -> list[Any]:
    """Apply imputation rules to a DataFrame using the ImputationEngine.

    This is a convenience wrapper around
    :meth:`ImputationEngine.apply <brewgis.workspace.services.imputation_engine.ImputationEngine.apply>`.

    Args:
        df: DataFrame with columns to impute (modified in place).
        rules: Imputation rules to apply (highest priority first).

    Returns:
        List of ImputationResult objects, one per rule.
    """
    engine = ImputationEngine()
    return engine.apply(df, rules)
