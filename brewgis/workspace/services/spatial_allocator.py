"""Spatial allocation engine — area-weighted proportional allocation between layers.

Allocates attributes from a source layer (e.g., census block groups) to a
target layer (e.g., parcels) by computing the area of intersection between
each source and target geometry, then proportionally distributing values.
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)


def allocate_attributes(
    source_schema: str,
    source_table: str,
    target_schema: str,
    target_table: str,
    columns: list[str],
    target_column_prefix: str = "",
    source_geom_col: str = "geom",
    target_geom_col: str = "geom",
    wm_srid: int = 3857,
) -> dict[str, Any]:
    """Allocate numeric attributes from source layer to target layer.

    For each target feature, the allocated value is the sum across all
    intersecting source features of (source_value * intersection_area / source_area).

    Uses direct SQL with the PostGIS ``public.intersection_acres`` and
    ``public.acres`` functions — no GeoDataFrame round-trip.

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
            total_features: Number of target feature-column pairs updated.
            allocated_columns: List of column names written.
            errors: List of any per-column errors.
    """
    engine = get_engine()
    errors: list[str] = []
    new_column_names: list[str] = []
    updated_count = 0

    with engine.begin() as conn:
        for col in columns:
            new_col = f"{target_column_prefix}{col}" if target_column_prefix else col
            new_column_names.append(new_col)

            # Add column if it doesn't exist
            conn.execute(
                text(
                    f'ALTER TABLE "{target_schema}"."{target_table}" '
                    f'ADD COLUMN IF NOT EXISTS "{new_col}" DOUBLE PRECISION DEFAULT 0'
                )
            )

            # Single UPDATE from allocation weight subquery
            # Pre-transform both geometries in subquery CTEs to use index-friendly
            # ST_Intersects on the projected SRID. Use the wm_srid parameter (default 3857).
            sql = text(f"""
                UPDATE "{target_schema}"."{target_table}" AS t
                SET "{new_col}" = sub.allocated_value
                FROM (
                    SELECT
                        t2.ctid,
                        SUM(
                            COALESCE(s."{col}", 0)
                            * public.intersection_acres(
                                s.geom_wm,
                                t2.geom_wm
                            )
                            / NULLIF(public.acres(s.geom_wm), 0)
                        ) AS allocated_value
                    FROM (
                        SELECT *, ST_Transform("{source_geom_col}", {wm_srid}) AS geom_wm
                        FROM "{source_schema}"."{source_table}"
                    ) s
                    JOIN (
                        SELECT ctid, *, ST_Transform("{target_geom_col}", {wm_srid}) AS geom_wm
                        FROM "{target_schema}"."{target_table}"
                    ) t2
                        ON ST_Intersects(s.geom_wm, t2.geom_wm)
                    WHERE public.acres(s.geom_wm) > 0
                      AND public.intersection_acres(s.geom_wm, t2.geom_wm) > 0
                    GROUP BY t2.ctid
                ) sub
                WHERE t.ctid = sub.ctid
            """)
            result = conn.execute(sql)
            updated_count += result.rowcount

    return {
        "total_features": updated_count,
        "allocated_columns": new_column_names,
        "errors": errors,
    }
