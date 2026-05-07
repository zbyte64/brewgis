"""Column stitching / imputation tool — fills missing values in target columns.

Supports multiple imputation strategies:
- constant: Fill with a fixed default value.
- area_proportional: Fill from a source layer using area-weighted allocation.
- built_form_default: Fill from the nearest matching built form definition.
"""
from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd
from django.db import connection

from brewgis.workspace.services.spatial_allocator import (
    _load_geometries_and_values,
)
from brewgis.workspace.services.spatial_allocator import (
    _compute_allocation_factors,
)

logger = logging.getLogger(__name__)


def impute_constant(
    schema: str,
    table: str,
    column: str,
    value: int | float,
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
            f'UPDATE "{schema}"."{table}" '
            f'SET "{column}" = %s '
            f'WHERE "{column}" IS NULL',
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
    # Load source data
    source_gdf = _load_geometries_and_values(
        source_schema, source_table, source_geom_col, [source_column],
    )
    source_gdf["__sid__"] = source_gdf.index

    # Load target data — only rows with NULL in target column
    query = (
        f'SELECT "{target_geom_col}", '
        f'"{target_column}" FROM "{schema}"."{target_table}" '
        f'WHERE "{target_column}" IS NULL'
    )
    null_targets = gpd.read_postgis(
        query, connection, geom_col=target_geom_col,
    )

    if null_targets.empty:
        return {
            "rows_updated": 0,
            "source_column": source_column,
            "target_column": target_column,
        }

    null_targets["__tid__"] = null_targets.index

    # Compute allocation weights
    allocation_df = _compute_allocation_factors(
        source_gdf, null_targets,
        source_id_col="__sid__", target_id_col="__tid__",
    )

    # Compute values per target row
    target_values: dict[int, float] = {}
    for _, row in allocation_df.iterrows():
        sid = int(row["__sid__"])
        tid = int(row["__tid__"])
        weight = row["weight"]
        source_val = source_gdf.loc[sid, source_column]
        if pd.isna(source_val):
            source_val = 0.0
        allocated = float(source_val) * weight
        target_values[tid] = target_values.get(tid, 0.0) + allocated

    # Write back
    rows_updated = 0
    query = (
        f'SELECT ctid FROM "{schema}"."{target_table}" '
        f'WHERE "{target_column}" IS NULL '
        f'ORDER BY ctid'
    )
    with connection.cursor() as cursor:
        cursor.execute(query)
        null_rows = cursor.fetchall()

        # Map by offset order
        null_offsets = {i: row[0] for i, row in enumerate(null_rows)}

        for tid, value in target_values.items():
            if tid in null_offsets:
                ctid = null_offsets[tid]
                cursor.execute(
                    f'UPDATE "{schema}"."{target_table}" '
                    f'SET "{target_column}" = %s '
                    f'WHERE ctid = %s',
                    [value, ctid],
                )
                rows_updated += 1

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
            f'SELECT column_name FROM information_schema.columns '
            f'WHERE table_schema = %s AND table_name = %s AND column_name = %s',
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
