from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmesh import macro

from brewgis.sqlmesh.crs import metres_per_unit
from brewgis.sqlmesh.crs import require_local_srid

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

# Re-exported here for the models and services that import them from this
# module; the definitions live in ``brewgis.sqlmesh.crs`` so that every macro
# module resolving them shares one object (see that module's docstring).
__all__ = ["metres_per_unit", "require_local_srid"]


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


@macro()
def local_srid(evaluator: MacroEvaluator) -> str:
    """Render ``local_srid`` as the bare integer literal to project a geometry into.

    The SQL face of :func:`require_local_srid`, for models that have to reproject
    a geometry into the CRS the ``*_local`` geometries and
    ``@metres_in_local_units`` radii are measured in — and which therefore must
    fail as loudly as they do when the variable is unset.

    Usage in model SQL::

        ST_Transform(es.geometry, @local_srid()) AS geometry
    """
    return str(require_local_srid(evaluator))
