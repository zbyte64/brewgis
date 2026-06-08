from __future__ import annotations

from sqlmesh import macro


@macro()
def constraint_acres(
    evaluator, table_name: str, geom_col: str = "geom", schema: str = "public"
) -> str:
    """Compute the overlap area in acres between a parcel and a constraint layer.

    Returns a SQL expression (scalar subquery) that computes the total
    intersection area in acres. 4046.86 sqm = 1 acre.

    Usage in model SQL::

        @constraint_acres('floodplains', 'geom')
        @constraint_acres('wetlands', 'geom', 'public')

    Args:
        table_name: Name of the constraint table.
        geom_col: Geometry column name (default: geom).
        schema: Schema containing the constraint table (default: public).

    Returns:
        SQL scalar subquery expression for constraint intersection acres.
    """
    return f"""COALESCE(
    (
        SELECT SUM(public.intersection_acres(p.geom, c.{geom_col}))
        FROM {schema}.{table_name} c
        WHERE ST_Intersects(p.geom, c.{geom_col})
    ),
    0.0
)"""


@macro()
def apply_constraint(
    evaluator,
    acres_before_expr: str,
    table_name: str,
    geom_col: str,
    discount_pct: str,
    schema: str = "public",
) -> str:
    """Compute the developable acres after applying a constraint discount.

    Returns a SQL expression::

        GREATEST(0, acres_before - overlap_acres * discount_pct / 100.0)

    Where overlap_acres is the area of intersection between parcel and constraint
    layer, and discount_pct is the percentage of that area to count against
    developable acreage (e.g., 100 for total loss, 50 for partial).

    Args:
        acres_before_expr: SQL expression for acres before constraint.
        table_name: Name of the constraint table.
        geom_col: Geometry column name.
        discount_pct: Discount percentage.
        schema: Schema containing the constraint table (default: public).

    Returns:
        SQL expression for developable acres after constraint.
    """
    return f"""public.clamp_non_negative(
    {acres_before_expr}
    - (
        COALESCE(
            (
                SELECT SUM(public.intersection_acres(p.geom, c.{geom_col}))
                FROM {schema}.{table_name} c
                WHERE ST_Intersects(p.geom, c.{geom_col})
            ),
            0.0
        ) * {discount_pct} / 100.0
    )
)"""


@macro()
def compute_allocation_weight(
    evaluator,
    source_alias: str,
    target_alias: str,
    source_geom: str = "geom",
    target_geom: str = "geom",
) -> str:
    """Compute the area-weighted allocation factor between source and target geometries.

    Returns a SQL expression producing the ratio of intersection area to source
    area -- the fraction of each source geometry's area that overlaps a target
    Both geometries are projected to wm_srid for area measurement.
    The 4046.86 acre-conversion factor cancels out in the division, so the result
    is a pure ratio in [0, 1].

    Usage in model SQL::

        SELECT @compute_allocation_weight('s', 't', 'geom_wm', 'geom_wm') AS weight
        FROM source_wm s
        JOIN target_wm t
            ON ST_Intersects(s.geom_wm, t.geom_wm)

    Args:
        source_alias: Table alias for the source geometry.
        target_alias: Table alias for the target geometry.
        source_geom: Source geometry column name (default: geom).
        target_geom: Target geometry column name (default: geom).

    Returns:
        SQL expression for allocation weight ratio.
    """
    return f"""public.intersection_acres(
    ST_Transform({source_alias}.{source_geom}, @variable('wm_srid', 3857)),
    ST_Transform({target_alias}.{target_geom}, @variable('wm_srid', 3857))
) / NULLIF(public.acres(ST_Transform({source_alias}.{source_geom}, @variable('wm_srid', 3857))), 0)"""
