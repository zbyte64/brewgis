from __future__ import annotations

from sqlmesh import macro


@macro()
def st_area_projected(evaluator, geom: str) -> str:
    """Compute projected area in acres using local_srid (CA Albers, SRID 3310).

    Uses the local_srid variable for accurate area calculations (default:
    3310, CA Albers). When local_srid is null, falls back to ST_Area on
    the input geometry (typically SRID 4326), which produces meaningless
    area values.

    local_srid is configured in the SQLMesh config (default: 3310 for
    California Albers). Override via @variable if needed.

    Usage in model SQL::

        @st_area_projected('p.geom')

    Args:
        geom: SQL expression for the geometry to compute area for.

    Returns:
        SQL expression computing area in acres using the projected CRS.
    """
    return f"public.acres(ST_Transform({geom}, @variable('local_srid', 3310)))"
