from __future__ import annotations

from typing import TYPE_CHECKING

from pyproj import CRS
from sqlmesh import macro

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.core.macros import MacroEvaluator


def metres_per_unit(srid: int) -> float:
    """Return how many metres one linear unit of projected CRS *srid* spans.

    ``local_srid`` is whatever projected CRS suits a region — CA Albers is in
    metres, most US State Plane zones are in US survey feet, some national grids
    use international feet — so a coordinate, a distance or an area measured in
    it is in *that CRS's* unit. Every conversion to a physical unit (km, acres)
    scales by this factor instead of assuming metres.

    The factor is read from the CRS definition itself (PROJ's EPSG registry —
    the same one PostGIS's ``spatial_ref_sys`` and DuckDB's ``'EPSG:<srid>'``
    transforms use), so it is correct for any projection without a per-region
    config value. A geographic CRS is refused: its unit is an angle, and
    planar distances or areas over degrees have no physical meaning.

    Raises:
        ValueError: *srid* is not a projected CRS, or its two axes are in
            different units (no single planar scale exists).
    """
    crs = CRS.from_epsg(srid)
    if not crs.is_projected:
        msg = f"SRID {srid} ({crs.name}) is not a projected CRS; planar distances and areas need one."
        raise ValueError(msg)
    factors = {axis.unit_conversion_factor for axis in crs.axis_info}
    if len(factors) != 1:
        msg = (
            f"SRID {srid} ({crs.name}) has axes in different units: {sorted(factors)}."
        )
        raise ValueError(msg)
    return factors.pop()


def require_local_srid(evaluator: MacroEvaluator | ExecutionContext) -> int:
    """Return the ``local_srid`` variable, refusing to guess a CRS when it is unset.

    *evaluator* is anything with SQLMesh's ``var(name)`` — a macro evaluator or
    a Python model's execution context.
    """
    srid = evaluator.var("local_srid")
    if srid is None:
        msg = "The local_srid variable is not set; projected measurements have no CRS to use."
        raise ValueError(msg)
    return int(srid)


@macro()
def st_area_projected(evaluator: MacroEvaluator, geom: str) -> str:
    """Compute a geometry's area in acres, measured in the region's ``local_srid``.

    The area is taken in ``local_srid`` (an equal-area or conformal local
    projection, so it is accurate for the region) and converted from that CRS's
    squared linear unit to square metres before the acre conversion — see
    :func:`metres_per_unit`. ``public.acres`` cannot be used here: it assumes
    the geometry's unit is the metre.

    Usage in model SQL::

        @st_area_projected(p.geometry)

    Args:
        geom: SQL expression for the geometry to compute area for.

    Returns:
        SQL expression computing area in acres.
    """
    srid = require_local_srid(evaluator)
    square_metres_per_unit = metres_per_unit(srid) ** 2
    return f"public.sqm_to_acres(ST_Area(ST_Transform({geom}, {srid})) * {square_metres_per_unit!r})"


# The three macros below are the SQL face of ``metres_per_unit`` for geometry
# already in ``local_srid`` (a ``local_geometry`` column): measure in the local
# CRS, then convert the *measurement*, never the geometry. The factor is a
# render-time literal, so the planner sees a constant (an ``ST_DWithin`` radius
# stays index-usable).


@macro()
def local_length_metres(evaluator: MacroEvaluator, length: str) -> str:
    """Convert a length measured in ``local_srid`` (``ST_Length``, ``ST_Distance``) to metres.

    Usage in model SQL::

        @local_length_metres(ST_Length(t.local_geometry)) AS length_m
    """
    return f"(({length}) * {metres_per_unit(require_local_srid(evaluator))!r})"


@macro()
def local_area_sqm(evaluator: MacroEvaluator, area: str) -> str:
    """Convert an area measured in ``local_srid`` (``ST_Area``) to square metres.

    Usage in model SQL::

        public.sqm_to_acres(@local_area_sqm(ST_Area(p.local_geometry))) AS acres
    """
    return f"(({area}) * {metres_per_unit(require_local_srid(evaluator)) ** 2!r})"


@macro()
def metres_in_local_units(evaluator: MacroEvaluator, metres: str) -> str:
    """Express a distance given in metres (a search radius, a snapping grid) in ``local_srid`` units.

    Usage in model SQL::

        ST_DWithin(p.centroid_local, i.geometry, @metres_in_local_units(402.0))
    """
    return f"(({metres}) / {metres_per_unit(require_local_srid(evaluator))!r})"
