"""Spatial allocation engine — area-weighted proportional allocation between layers.

Allocates attributes from a source layer (e.g., census block groups) to a
target layer (e.g., parcels) by computing the area of intersection between
each source and target geometry, then proportionally distributing values.
"""
from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import pandas as pd
from django.db import connection

logger = logging.getLogger(__name__)


def _load_geometries_and_values(
    schema: str,
    table: str,
    geom_col: str,
    value_columns: list[str] | None = None,
    include_ctid: bool = False,
) -> gpd.GeoDataFrame:
    """Load geometries and optional value columns from a PostGIS table.

    Args:
        schema: Database schema name.
        table: Table name.
        geom_col: Geometry column name (typically 'geom' or 'geometry').
        value_columns: List of numeric columns to load. None = load all.
        include_ctid: If True, include ctid AS __ctid__ for row identity.

    Returns:
        GeoDataFrame with geometry and value columns, plus __ctid__ if requested.
    """
    extra_cols = []
    if include_ctid:
        extra_cols.append("ctid AS __ctid__")

    if value_columns:
        if extra_cols:
            cols = ", ".join(extra_cols + value_columns)
        else:
            cols = ", ".join(value_columns)
        query = f'SELECT "{geom_col}", {cols} FROM "{schema}"."{table}"'
    else:
        ctid_clause = ", ctid AS __ctid__" if include_ctid else ""
        query = f'SELECT *{ctid_clause} FROM "{schema}"."{table}"'

    df = gpd.read_postgis(query, connection, geom_col=geom_col)
    return df


def _compute_allocation_factors(
    source_gdf: gpd.GeoDataFrame,
    target_gdf: gpd.GeoDataFrame,
    source_id_col: str = "__sid__",
    target_id_col: str = "__tid__",
) -> pd.DataFrame:
    """Compute area-weighted allocation factors between source and target.

    For each source-target pair, computes the intersection area as a fraction
    of the source geometry area. This gives the weight for distributing source
    values to each intersecting target.

    Args:
        source_gdf: Source layer GeoDataFrame. Must have __sid__ index column.
        target_gdf: Target layer GeoDataFrame. Must have __tid__ index column.
        source_id_col: Name of the source ID column (default: __sid__).
        target_id_col: Name of the target ID column (default: __tid__).

    Returns:
        DataFrame with columns: {source_id_col}, {target_id_col}, weight.
    """
    # Ensure both are in the same CRS and projected for area calculation
    if source_gdf.crs != target_gdf.crs:
        if source_gdf.crs is None and target_gdf.crs is not None:
            source_gdf = source_gdf.set_crs(target_gdf.crs)
        elif target_gdf.crs is None and source_gdf.crs is not None:
            target_gdf = target_gdf.set_crs(source_gdf.crs)

    if source_gdf.crs:
        # Reproject to a projected CRS for accurate area calculations
        # Use UTM zone if possible, or fall back to web mercator
        projected_crs = "EPSG:3857"
        try:
            source_proj = source_gdf.to_crs(projected_crs)
            target_proj = target_gdf.to_crs(projected_crs)
        except Exception:
            source_proj = source_gdf
            target_proj = target_gdf
    else:
        source_proj = source_gdf
        target_proj = target_gdf

    # Compute total source areas
    source_areas = source_proj.geometry.area

    allocation_rows: list[dict[str, Any]] = []

    # Spatial join: for each source, find overlapping targets
    for source_idx, source_row in source_proj.iterrows():
        source_geom = source_row.geometry
        source_area = source_areas.loc[source_idx]
        if source_area <= 0:
            continue

        # Find targets that intersect this source
        for target_idx, target_row in target_proj.iterrows():
            target_geom = target_row.geometry
            if source_geom.intersects(target_geom):
                try:
                    intersection = source_geom.intersection(target_geom)
                    intersection_area = intersection.area
                except Exception:
                    continue

                if intersection_area > 0:
                    weight = intersection_area / source_area
                    allocation_rows.append({
                        source_id_col: source_idx,
                        target_id_col: target_idx,
                        "weight": weight,
                    })

    if not allocation_rows:
        msg = "No spatial overlaps found between source and target layers."
        raise RuntimeError(msg)

    return pd.DataFrame(allocation_rows)


def allocate_attributes(
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    columns: list[str],
    target_column_prefix: str = "",
    source_geom_col: str = "geom",
    target_geom_col: str = "geom",
) -> dict[str, Any]:
    """Allocate numeric attributes from source layer to target layer.

    For each target feature, the allocated value is the sum across all
    intersecting source features of (source_value * intersection_area / source_area).

    Args:
        source_schema: Schema of the source table.
        source_table: Source table (e.g., census block groups).
        target_schema: Schema of the target table.
        target_table: Target table (e.g., parcels).
        columns: Numeric column names to allocate.
        target_column_prefix: Optional prefix for new columns on target.
        source_geom_col: Geometry column on source (default: geom).
        target_geom_col: Geometry column on target (default: geom).

    Returns:
        Dict with keys:
            total_features: Number of target features updated.
            allocated_columns: List of column names written.
            errors: List of any per-column errors.
    """
    # Load source data
    source_gdf = _load_geometries_and_values(
        source_schema, source_table, source_geom_col, columns,
    )
    source_gdf["__sid__"] = source_gdf.index

    target_gdf = _load_geometries_and_values(
        target_schema, target_table, target_geom_col, include_ctid=True,
    )
    target_gdf["__tid__"] = target_gdf.index
    # Map tid to physical row identity
    tid_to_ctid = target_gdf["__ctid__"].to_dict()

    # Compute allocation weights
    allocation_df = _compute_allocation_factors(
        source_gdf, target_gdf,
        source_id_col="__sid__", target_id_col="__tid__",
    )

    # For each column, compute allocated values per target
    target_values: dict[int, dict[str, float]] = {}
    for col in columns:
        if col not in source_gdf.columns:
            continue

        col_values: dict[int, float] = {}
        for _, row in allocation_df.iterrows():
            sid = int(row["__sid__"])
            tid = int(row["__tid__"])
            weight = row["weight"]
            source_val = source_gdf.loc[sid, col]
            if pd.isna(source_val):
                source_val = 0.0
            allocated = float(source_val) * weight
            col_values[tid] = col_values.get(tid, 0.0) + allocated

        target_values[col] = col_values

    # Write results back to target table
    errors: list[str] = []
    updated_count = 0
    new_column_names: list[str] = []

    with connection.cursor() as cursor:
        for col in columns:
            if col not in target_values:
                continue

            new_col = f"{target_column_prefix}{col}" if target_column_prefix else col
            new_column_names.append(new_col)

            # Add column if it doesn't exist
            try:
                cursor.execute(
                    f'ALTER TABLE "{target_schema}"."{target_table}" '
                    f'ADD COLUMN IF NOT EXISTS "{new_col}" DOUBLE PRECISION DEFAULT 0'
                )
            except Exception as e:
                errors.append(f"Failed to add column {new_col}: {e}")
                continue

            for tid, value in target_values[col].items():
                try:
                    ctid = tid_to_ctid[tid]
                    cursor.execute(
                        f'UPDATE "{target_schema}"."{target_table}" '
                        f'SET "{new_col}" = %s '
                        f'WHERE ctid = %s',
                        [value, ctid],
                    )
                    updated_count += 1
                except Exception as e:
                    errors.append(f"Failed to update {new_col} for row {tid}: {e}")

    return {
        "total_features": updated_count,
        "allocated_columns": new_column_names,
        "errors": errors,
    }
