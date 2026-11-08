"""A workspace's extent — the area its public analysis inputs are fetched over.

The extent is the bounding box of the workspace's base layer in EPSG:4326. The
per-workspace fetch models (``sqlmesh/macros/workspace_blueprints.py``) bake its
four coordinates into their queries, so the box is rounded *outward* to a fixed
grid: the same table always yields the same text (and therefore the same model
fingerprint), and the rounding can only widen the box, never drop a parcel at its
edge.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from django.contrib.gis.geos import Polygon
from django.db import connection

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace

#: Decimal places the extent is rounded to (1e-5 degrees is about a metre).
EXTENT_DECIMALS = 5


def _floor(value: float) -> float:
    scale = 10**EXTENT_DECIMALS
    return math.floor(value * scale) / scale


def _ceil(value: float) -> float:
    scale = 10**EXTENT_DECIMALS
    return math.ceil(value * scale) / scale


def extent_polygon(xmin: float, ymin: float, xmax: float, ymax: float) -> Polygon:
    """The EPSG:4326 box over ``(xmin, ymin, xmax, ymax)``, rounded outward."""
    return Polygon.from_bbox((_floor(xmin), _floor(ymin), _ceil(xmax), _ceil(ymax)))


def extent_bounds(extent: Polygon) -> tuple[float, float, float, float]:
    """``(xmin, ymin, xmax, ymax)`` of a stored extent."""
    xmin, ymin, xmax, ymax = extent.extent
    return (float(xmin), float(ymin), float(xmax), float(ymax))


def base_table_extent(base_table: str) -> Polygon | None:
    """The rounded EPSG:4326 bounding box of *base_table*'s ``geometry`` column.

    ``None`` when the table has no ``geometry`` column (or does not exist) or no
    geometry rows — a workspace without an extent gets no analysis inputs, and
    its launches are refused as not configured for analysis.
    """
    schema, _, table = base_table.rpartition(".")
    schema = schema or "public"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = 'geometry'",
            [schema, table],
        )
        if cursor.fetchone() is None:
            return None
        quoted = ".".join(
            '"' + part.replace('"', '""') + '"' for part in (schema, table)
        )
        extent_sql = (
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "  # noqa: S608 — quoted identifiers
            f"(SELECT ST_Extent(ST_Transform(geometry, 4326)) AS e FROM {quoted}) AS x"
        )
        cursor.execute(extent_sql)
        row = cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return extent_polygon(*row)


class WorkspaceInputsError(ValueError):
    """The workspace is not configured for analysis: it has no analysis inputs."""


def workspace_inputs_error(workspace: Workspace) -> str | None:
    """Why *workspace* cannot be analyzed, or ``None`` when it can.

    A scenario's analysis reads the workspace's own input models
    (``sqlmesh/macros/workspace_blueprints.py``), which exist only for a
    workspace with an extent: without one there is no area to fetch public
    inputs over. There is deliberately no default area to substitute.
    """
    if workspace.extent is None:
        return (
            f"Workspace {workspace.pk} ({workspace.name}) is not configured for "
            f"analysis: its base table {workspace.base_table!r} has no geometry to "
            "take an extent from, so it has no analysis inputs. Set the "
            "workspace's base table to a loaded base canvas."
        )
    return None
