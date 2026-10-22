"""The SACOG v1 database snapshot as a workspace package.

The UrbanFootprint v1 dump (restored into ``public`` by ``restore_demo_db``)
carries a region base canvas and the data UrbanFootprint analyzed it against.
This module writes it as a standard workspace package
(``services.workspace_package``), which ``import_sacog_demo`` attaches to the
*SACOG v1* workspace — the same import path any other server's export takes, so
the snapshot is not a special case anywhere downstream:

- ``base_canvas`` — ``public.sac_cnty_region_base_canvas`` projected onto the
  base-canvas contract by ``sacog_column_mapping.build_materialized_select_sql``
  (the parcel key is the v1 ``geography_id``);
- ``constraint_layers`` — the three layers UrbanFootprint's environmental
  constraint module reads for SACOG (streams, wetlands, vernal pools), each
  taking the whole overlap (100 %), so the snapshot's constrained acreage stays
  comparable with UrbanFootprint's export. The dump stores them in CA Albers
  (EPSG:3310);
- ``trip_length_zones`` — SACSIM's zone trip lengths, which cover the whole
  SACOG region despite the table's Elk Grove name;
- ``built_forms`` — the workspace's Building Type library (seeded, then
  completed with the v1 built forms by ``sacog_built_form_extractor``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.sacog_column_mapping import V1_BASE_TABLE
from brewgis.workspace.services.sacog_column_mapping import (
    build_materialized_select_sql,
)
from brewgis.workspace.services.workspace_extent import extent_bounds
from brewgis.workspace.services.workspace_extent import extent_polygon
from brewgis.workspace.services.workspace_package import PartKind
from brewgis.workspace.services.workspace_package import built_forms_document
from brewgis.workspace.services.workspace_package import export_geoparquet_parts
from brewgis.workspace.services.workspace_package import write_built_forms
from brewgis.workspace.services.workspace_package import write_package

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace

#: The CRS the dump stores its geometries in, with no SRID recorded on some.
V1_SRID = 3310

#: ``(layer name, source table)`` — the snapshot's environmental constraints.
V1_CONSTRAINT_LAYERS: tuple[tuple[str, str], ...] = (
    ("streams", "public.sac_cnty_streams"),
    ("wetlands", "public.sac_cnty_wetlands"),
    ("vernal_pools", "public.sac_cnty_vernal_pools"),
)
V1_TRIP_LENGTH_TABLE = "public.elk_grove_vmt_base_trip_lengths"
_TRIP_LENGTH_COLUMNS = (
    "productions_hbw",
    "productions_hbo",
    "productions_nhb",
    "attractions_hbw",
    "attractions_hbo",
    "attractions_nhb",
)


def _base_canvas_query() -> str:
    projected = build_materialized_select_sql(V1_BASE_TABLE)
    columns = [
        f'"{name}"' for name in BaseCanvasSchema.COLUMN_NAMES if name != "geometry"
    ]
    return f"SELECT {', '.join(columns)}, ST_AsBinary(geometry) AS wkb FROM ({projected}) AS v1"  # noqa: S608 — project-built SQL


def _in_4326(geometry: str) -> str:
    """The dump's 3310 geometry in EPSG:4326 (tagged first: not every table records it)."""
    return f"ST_Transform(ST_SetSRID({geometry}, {V1_SRID}), 4326)"


def _constraint_layers_query() -> str:
    return " UNION ALL ".join(
        f"SELECT '{layer}'::text AS layer, 100.0::double precision AS discount_pct, "  # noqa: S608 — project constants
        f"ST_AsBinary({_in_4326('wkb_geometry')}) AS wkb FROM {table} WHERE wkb_geometry IS NOT NULL"
        for layer, table in V1_CONSTRAINT_LAYERS
    )


def _trip_length_zones_query() -> str:
    columns = ", ".join(
        f"{name}::double precision AS {name}" for name in _TRIP_LENGTH_COLUMNS
    )
    return (
        f"SELECT {columns}, ST_AsBinary(ST_Multi({_in_4326('wkb_geometry')})) AS wkb "  # noqa: S608 — project constants
        f"FROM {V1_TRIP_LENGTH_TABLE} WHERE wkb_geometry IS NOT NULL"
    )


def _base_canvas_extent() -> tuple[float, float, float, float]:
    projected = build_materialized_select_sql(V1_BASE_TABLE)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "  # noqa: S608 — project-built SQL
            f"(SELECT ST_Extent(geometry) AS e FROM ({projected}) AS v1) AS x"
        )
        row = cursor.fetchone()
    if row is None or row[0] is None:
        msg = f"{V1_BASE_TABLE} has no geometry: restore the v1 dump first (restore_demo_db)."
        raise ValueError(msg)
    return extent_bounds(extent_polygon(*row))


def build_sacog_v1_package(workspace: Workspace, destination: Path) -> Path:
    """Write the v1 snapshot, with *workspace*'s Building Types, as a package at *destination*."""
    with tempfile.TemporaryDirectory(prefix="brewgis-sacog-v1-") as tmp:
        directory = Path(tmp)
        parts = export_geoparquet_parts(
            {
                PartKind.BASE_CANVAS: (_base_canvas_query(), "geometry"),
                PartKind.CONSTRAINT_LAYERS: (_constraint_layers_query(), "geometry"),
                PartKind.TRIP_LENGTH_ZONES: (_trip_length_zones_query(), "geometry"),
            },
            directory,
        )
        parts.append(write_built_forms(built_forms_document(workspace), directory))
        return write_package(
            manifest_fields={
                "name": workspace.name,
                "local_srid": V1_SRID,
                "extent": _base_canvas_extent(),
                "center_lng": workspace.center_lng,
                "center_lat": workspace.center_lat,
                "zoom": workspace.zoom,
                "fill_built_form": False,
            },
            parts=parts,
            directory=directory,
            destination=destination,
        )
