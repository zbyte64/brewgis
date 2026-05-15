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
from brewgis.workspace.services._db import get_engine, text


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


def impute_area_proportional(
    schema: str,
    target_table: str,
    target_column: str,
    source_schema: str,
    source_table: str,
    source_column: str,
    source_geom_col: str = "geom",
    target_geom_col: str = "geom",
) -> dict[str, Any]:
    """Fill NULL values in target column using area-weighted values from source.

    For each target row with NULL in target_column, computes the area-weighted
    sum of source_column from intersecting source features.

    Args:
        schema: Shared schema for source and target.
        target_table: Target table with missing values.
        target_column: Column to fill.
        source_schema: Source layer schema.
        source_table: Source layer table.
        source_column: Numeric column on source to use for filling.
        source_geom_col: Geometry column on source.
        target_geom_col: Geometry column on target.

    Returns:
        Dict with keys: rows_updated, source_column, target_column.
    """
    engine = get_engine()

    with engine.begin() as conn:
        result = conn.execute(
            text(f"""
                UPDATE "{schema}"."{target_table}" AS t
                SET "{target_column}" = sub.allocated_value
                FROM (
                    SELECT
                        nt.ctid,
                        SUM(
                            COALESCE(s."{source_column}", 0)
                            * public.intersection_acres(
                                ST_Transform(s."{source_geom_col}", 3857),
                                ST_Transform(nt."{target_geom_col}", 3857)
                            )
                            / NULLIF(public.acres(ST_Transform(s."{source_geom_col}", 3857)), 0)
                        ) AS allocated_value
                    FROM (
                        SELECT ctid, "{target_geom_col}"
                        FROM "{schema}"."{target_table}"
                        WHERE "{target_column}" IS NULL
                    ) nt
                    JOIN "{source_schema}"."{source_table}" s
                        ON ST_Intersects(
                            ST_Transform(s."{source_geom_col}", 3857),
                            ST_Transform(nt."{target_geom_col}", 3857)
                        )
                    WHERE public.acres(ST_Transform(s."{source_geom_col}", 3857)) > 0
                      AND public.intersection_acres(
                          ST_Transform(s."{source_geom_col}", 3857),
                          ST_Transform(nt."{target_geom_col}", 3857)
                      ) > 0
                    GROUP BY nt.ctid
                ) sub
                WHERE t.ctid = sub.ctid
            """)
        )
        rows_updated = result.rowcount

    return {
        "rows_updated": rows_updated,
        "source_column": source_column,
        "target_column": target_column,
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
