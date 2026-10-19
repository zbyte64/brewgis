"""Spatial helper macros for the analysis models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlmesh import macro

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# Constraint polygons smaller than this are ignored. A polygon that only clips a
# parcel's boundary is noise, not a constraint: on the SACOG canvas the raw
# intersections flag 2,153 parcels, and the sub-5 m2 slivers
# (UrbanFootprint's own threshold, `environmental_constraint_union_tool.py`)
# account for 1,046 of them while contributing 0.05 acres of overlap.
_MIN_OVERLAP_SQM = 5.0


@macro()
def constraint_min_overlap_sqm(evaluator: MacroEvaluator) -> str:  # noqa: ARG001
    """Render the minimum constraint overlap (in m2) the models filter on."""
    return repr(_MIN_OVERLAP_SQM)


def _number_text(value: exp.Expr) -> str:
    """The numeric literal *value* as written (``36.60`` keeps its zero)."""
    if isinstance(value, exp.Neg):
        return "-" + _number_text(value.this)
    if isinstance(value, exp.Literal) and not value.is_string:
        return value.this
    msg = f"Expected a numeric literal, got {value.sql()!r}"
    raise TypeError(msg)


@macro()
def arcgis_envelope(
    evaluator: MacroEvaluator,  # noqa: ARG001
    min_x: exp.Expr,
    min_y: exp.Expr,
    max_x: exp.Expr,
    max_y: exp.Expr,
) -> str:
    """Render a region bounding box as an ArcGIS envelope JSON string literal.

    For ``arcgis_query``'s ``query_params := MAP {'geometry': …}``: a table
    function takes constant arguments, so the JSON is assembled at render time
    from the region blueprint's ``overture_bbox_*`` values. The numbers keep
    their literal text, so the request — and the arcgis extension's on-disk
    cache entry keyed on it — is the same one a hand-written envelope makes.
    """
    envelope = (
        f'{{"xmin":{_number_text(min_x)},"ymin":{_number_text(min_y)},'
        f'"xmax":{_number_text(max_x)},"ymax":{_number_text(max_y)}}}'
    )
    return "'" + envelope + "'"


@macro()
def compute_allocation_weight(
    evaluator: MacroEvaluator,
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
    wm_srid = evaluator.var("wm_srid", 3857)
    return f"""public.intersection_acres(
    ST_Transform({source_alias}.{source_geom}, {wm_srid}),
    ST_Transform({target_alias}.{target_geom}, {wm_srid})
) / NULLIF(public.acres(ST_Transform({source_alias}.{source_geom}, {wm_srid})), 0)"""
