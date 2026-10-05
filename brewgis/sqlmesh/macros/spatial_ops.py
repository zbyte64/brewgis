"""Spatial helper macros for the analysis models.

``constraint_geometries`` is what ``models/analysis/env_constraint.sql`` builds
on: it expands a scenario's constraint configuration (``Scenario.constraints``,
a list of ``{table, discount_pct, geom_col}``) into one relation of constraint
polygons tagged with the share of each overlap that comes off developable
acreage. The configuration is per-scenario data, so the relation cannot be
expressed in static SQL — the table names are only known at render time, which
is what makes this a macro rather than a model of its own.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from sqlmesh import macro

from brewgis.sqlmesh.macros.geometry import require_local_srid

if TYPE_CHECKING:
    from sqlglot import exp
    from sqlmesh.core.macros import MacroEvaluator

# A constraint table's name and its geometry column: one to three dot-separated
# plain identifiers. Scenario-owned configuration, but it is spliced into SQL,
# so anything that is not a plain identifier (a quote, a semicolon, a hyphen) is
# refused rather than quoted. Typed by the analysis forms and the MCP launcher.
#
# A pattern *string*, not a compiled pattern: this module is a macro, so SQLMesh
# serializes it into a model's python_env, and a compiled regex cannot be.
_IDENTIFIER_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
_MAX_NAME_PARTS = 3
_MAX_DISCOUNT_PCT = 100.0

# The CRS the overlap is *tested* in. Constraints are tested against the parcel
# geometry as it is stored (EPSG:4326 on every base canvas), so the predicate
# `ST_Intersects(<probe>, parcel.geometry)` can drive the GiST index the canvas
# carries. The overlap itself is measured in the region's `local_srid`, never
# here: a geographic CRS has no planar area.
_PROBE_SRID = 4326

# Constraint polygons smaller than this are ignored. A polygon that only clips a
# parcel's boundary is noise, not a constraint: on the SACOG canvas the raw
# intersections flag 2,153 parcels, and the sub-5 m2 slivers
# (UrbanFootprint's own threshold, `environmental_constraint_union_tool.py`)
# account for 1,046 of them while contributing 0.05 acres of overlap.
_MIN_OVERLAP_SQM = 5.0


def _quoted(name: str, *, field: str) -> str:
    """Render a dot-separated identifier path, double-quoting each part.

    Raises:
        ValueError: *name* is not one to three plain identifiers.
    """
    parts = name.split(".")
    if not 1 <= len(parts) <= _MAX_NAME_PARTS or not all(
        re.fullmatch(_IDENTIFIER_PATTERN, part) for part in parts
    ):
        msg = f"Constraint {field} is not a plain SQL identifier: {name!r}"
        raise ValueError(msg)
    return ".".join(f'"{part}"' for part in parts)


@macro()
def constraint_geometries(
    evaluator: MacroEvaluator, constraints_json: str
) -> exp.Expression:
    """Expand a scenario's constraint configuration into a polygon relation.

    Returns a subquery with one row per constraint polygon:

    - ``probe_geom``: the polygon in EPSG:4326, for the index-driven
      ``ST_Intersects`` against the parcel geometry;
    - ``local_geom``: the polygon in the region's ``local_srid``, for
      ``ST_Intersection`` and the area measurement;
    - ``discount_pct``: the share of the overlap that comes off developable
      acreage (100 = the whole overlap).

    Args:
        constraints_json: ``Scenario.constraints`` as JSON —
            ``[{table, discount_pct, geom_col}]``; ``table`` is a bare name
            (resolved in ``public``) or a ``schema.table`` path, ``geom_col``
            defaults to ``geom``, and an empty list yields the empty relation,
            so a scenario with no constraints keeps its whole gross area
            developable.

    Raises:
        ValueError: the JSON is malformed, an entry is not an object, a name is
            not a plain identifier, or a discount is outside 0-100.
    """
    try:
        constraints = json.loads(constraints_json or "[]")
    except (TypeError, ValueError) as exc:
        msg = f"Scenario constraints is not valid JSON: {constraints_json!r}"
        raise ValueError(msg) from exc
    if not isinstance(constraints, list):
        msg = f"Scenario constraints must be a JSON list, got {type(constraints).__name__}"
        raise TypeError(msg)

    local_srid = require_local_srid(evaluator)
    selects: list[str] = []
    for entry in constraints:
        if not isinstance(entry, dict):
            msg = f"Scenario constraint entry is not an object: {entry!r}"
            raise TypeError(msg)
        table = str(entry.get("table") or "")
        if not table:
            msg = f"Scenario constraint entry names no table: {entry!r}"
            raise ValueError(msg)
        geom_col = str(entry.get("geom_col") or "geom")
        discount = float(entry.get("discount_pct", _MAX_DISCOUNT_PCT))
        if not 0.0 <= discount <= _MAX_DISCOUNT_PCT:
            msg = f"Constraint discount_pct must be between 0 and 100: {discount}"
            raise ValueError(msg)
        geom = _quoted(geom_col, field="geom_col")
        # Every interpolated value is either a name `_quoted` has validated as
        # plain identifiers or a float bound above, never raw scenario text.
        selects.append(
            f"SELECT ST_Transform({geom}, {_PROBE_SRID}) AS probe_geom,"  # noqa: S608
            f" ST_Transform({geom}, {local_srid}) AS local_geom,"
            f" {discount!r}::double precision AS discount_pct"
            f" FROM {_quoted(table, field='table')}"
        )

    if not selects:
        # No configured constraints: an empty relation of the same shape, so the
        # consuming model's LATERAL and its column references stay valid.
        return evaluator.parse_one(
            "(SELECT NULL::geometry AS probe_geom, NULL::geometry AS local_geom,"
            " 0.0::double precision AS discount_pct WHERE FALSE)"
        )
    return evaluator.parse_one("(" + " UNION ALL ".join(selects) + ")")


@macro()
def constraint_min_overlap_sqm(evaluator: MacroEvaluator) -> str:  # noqa: ARG001
    """Render the minimum constraint overlap (in m2) the models filter on."""
    return repr(_MIN_OVERLAP_SQM)


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
