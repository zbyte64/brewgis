"""CRS helpers shared by the macro modules.

These live *outside* ``macros/`` on purpose. SQLMesh loads every module under
``macros/`` a second time, by folder basename (``macros.geometry``) as well as
through the package path the repo's own code uses
(``brewgis.sqlmesh.macros.geometry``), so a helper that two macro modules both
import from inside that folder resolves to two distinct function objects. A
model that pulls a macro from each module (``env_constraint.sql`` takes
``@constraint_min_overlap_sqm`` from ``spatial_ops`` and ``@local_srid`` from
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


def require_workspace_srid(evaluator: MacroEvaluator | ExecutionContext) -> int:
    """Return the model's workspace CRS: its ``local_srid`` *blueprint* variable.

    Every workspace-scoped model — a scenario's analysis models, a workspace's
    ``wsp<pk>`` input models, a layer filter's models — is blueprinted from a
    row whose workspace names its own projected CRS (``Workspace.local_srid``),
    and measures in that CRS. There is no fallback to the project-wide
    ``local_srid`` variable, which only the region construction pipeline reads
    (see :func:`require_local_srid`): a workspace's measurements are never taken
    in another area's CRS.

    *evaluator* is anything with SQLMesh's ``blueprint_var(name)`` — a macro
    evaluator or a Python model's execution context.
    """
    srid = evaluator.blueprint_var("local_srid")
    if srid is None:
        msg = (
            "The local_srid blueprint variable is not set; a workspace-scoped model "
            "has no workspace CRS to measure in."
        )
        raise ValueError(msg)
    # A SQL model's macro evaluator hands blueprint values over as the sqlglot
    # literal they were rendered to; a Python model's context as the value.
    return int(getattr(srid, "name", srid))


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
