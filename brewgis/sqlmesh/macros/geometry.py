from __future__ import annotations

from sqlmesh import macro


@macro()
def st_area_projected(evaluator, geom: str) -> str:
    """Compute projected area in acres using the configured projected_srid.

    Uses the @projected_srid variable for accurate area calculations. When
    projected_srid is null, falls back to ST_Area on the input geometry
    (typically SRID 4326), which produces meaningless area values.

    projected_srid is configured in the SQLMesh config (default: 32611 for
    UTM zone 11N). Override via @variable if needed.

    Usage in model SQL::

        @st_area_projected('p.geom')

    Args:
        geom: SQL expression for the geometry to compute area for.

    Returns:
        SQL expression computing area in acres using the projected CRS.
    """
    return f"public.acres(ST_Transform({geom}, @variable('projected_srid', 32611)))"
