"""CRS helpers shared by the macro modules.

These live *outside* ``macros/`` on purpose. SQLMesh loads every module under
``macros/`` a second time, by folder basename (``macros.geometry``) as well as
through the package path the repo's own code uses
(``brewgis.sqlmesh.macros.geometry``), so a helper that two macro modules both
import from inside that folder resolves to two distinct function objects. A
model that pulls a macro from each module (``env_constraint.sql`` takes
``@constraint_geometries`` from ``spatial_ops`` and ``@local_srid`` from
``geometry``) then fails SQLMesh's python-env walk with ``duplicate definitions
found`` — on every model load after the first in a process. A single import
path keeps one object.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyproj import CRS

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
