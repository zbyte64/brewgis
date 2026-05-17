"""dlt pipeline for OSM (OpenStreetMap) intersection density.

Reads parcel geometries from a PostGIS table, downloads the OSM road
network for the study area via osmnx, computes intersection density
(intersections per square mile) per parcel, and writes to a staging
table for dbt consumption.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import osmnx as ox
import shapely

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

_DEFAULT_DENSITY = 12.5
_SQ_METERS_PER_SQ_MILE = 2_589_988.11
_TARGET_TABLE = "osm_intersection_density"


def _compute_jurisdiction_density(
    boundary: gpd.GeoDataFrame,
) -> float:
    """Compute intersection density (intersections / sq mi) for a boundary.

    Downloads the OSM driving road network within the boundary, identifies
    intersections (nodes with street_count >= 3), and computes density
    per square mile.

    Parameters
    ----------
    boundary : gpd.GeoDataFrame
        Single-row GeoDataFrame whose geometry defines the study area.

    Returns
    -------
    float
        Intersections per square mile, or ``0.0`` when no intersections found.
        Exceptions propagate to the caller — no exception is swallowed.
    """
    # osmnx expects geos to be EPSG:4326
    # Union all parcel geometries in the boundary then fix self-intersections
    # and simplify micro-vertices that can become degenerate on reprojection.
    geom = boundary.to_crs('EPSG:4326').union_all().buffer(0.001)
    geom = shapely.make_valid(geom)
    # handled by osmnx?
    # geom = geom.simplify(tolerance=15.0, preserve_topology=True)

    # Get the road network within the boundary
    graph = ox.graph_from_polygon(
        geom,
        network_type="drive",
        simplify=True,
        retain_all=True,
    )

    # Count intersections (nodes with street_count >= 3)
    # ValueError: Graph with no edges means ...?
    nodes, _ = ox.graph_to_gdfs(graph)
    intersections = nodes[nodes["street_count"] >= 3]

    # Compute area in square miles
    # TODO projection should be keyed to the workspace's local projection setting
    boundary_aea = boundary.to_crs("EPSG:6933") 
    area_sq_m = boundary_aea.area.sum()
    area_sq_mi = area_sq_m / _SQ_METERS_PER_SQ_MILE

    if area_sq_mi > 0 and len(intersections) > 0:
        return float(len(intersections) / area_sq_mi)

    return 0.0


def run_osm_pipeline(
    parcel_table: str,
    *,
    schema: str = "public",
) -> dict:
    """Compute OSM intersection density per parcel and write to staging table.

    Reads parcels from *parcel_table*, groups by jurisdiction (if the
    column exists), downloads the OSM driving network for each group,
    and writes ``parcel_id`` + ``intersection_density`` to
    ``{schema}.osm_intersection_density``.

    Parameters
    ----------
    parcel_table : str
        Name of the PostGIS table containing parcel geometries with a
        ``parcel_id`` column.
    schema : str, optional
        Database schema (default ``"public"``).

    Returns
    -------
    dict
        ``{"success": True, "table_name": str, "row_count": int}``
        on success, or ``{"success": False, "error": str}`` on failure.
    """
    try:
        # ── Read parcels as GeoDataFrame ──────────────────────────────
        sql = (
            f"SELECT parcel_id, geometry FROM {schema}.{parcel_table} "
            f"WHERE geometry IS NOT NULL"
        )
        parcels: gpd.GeoDataFrame = gpd.GeoDataFrame.from_postgis(
            sql, get_engine(), geom_col="geometry"
        )

        if parcels.empty:
            return {
                "success": False,
                "error": f"No parcels found in {schema}.{parcel_table}",
            }

        logger.info(
            "OSM pipeline: read %d parcels from %s.%s",
            len(parcels),
            schema,
            parcel_table,
        )

        # Check for optional jurisdiction column
        with get_engine().connect() as conn:
            result = conn.execute(
                text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_schema = '{schema}' "
                    f"AND table_name = '{parcel_table}' "
                    f"AND column_name = 'jurisdiction'"
                )
            )
            has_jurisdiction = result.fetchone() is not None

        # ── Compute density per jurisdiction or globally ──────────────
        if has_jurisdiction:
            # Re-read with jurisdiction column
            sql_juris = (
                f"SELECT parcel_id, geometry, jurisdiction "
                f"FROM {schema}.{parcel_table} WHERE geometry IS NOT NULL"
            )
            parcels = gpd.GeoDataFrame.from_postgis(
                sql_juris, get_engine(), geom_col="geometry"
            )
            # Needed? parcels.to_crs(src.crs)

            jurisdictions = parcels["jurisdiction"].unique()
            juris_density_map: dict[str, float] = {}

            for juris in jurisdictions:
                mask = parcels["jurisdiction"] == juris
                juris_parcels = parcels[mask]
                density = _compute_jurisdiction_density(juris_parcels)
                juris_density_map[str(juris)] = density

            parcels["intersection_density"] = (
                parcels["jurisdiction"].map(juris_density_map).round(2)
            )
        else:
            # Global density for the entire study area
            density = _compute_jurisdiction_density(parcels)
            parcels["intersection_density"] = np.round(density, 2)

        # ── Write to staging table ────────────────────────────────────
        target_table = f"{schema}.{_TARGET_TABLE}"
        parcels[["parcel_id", "intersection_density"]].to_sql(
            _TARGET_TABLE,
            get_engine(),
            schema=schema,
            if_exists="replace",
            index=False,
            method="multi",
        )

        row_count = len(parcels)

        logger.info(
            "OSM pipeline complete: %d rows written to %s",
            row_count,
            target_table,
        )

        return {
            "success": True,
            "table_name": target_table,
            "row_count": row_count,
        }

    except Exception:
        logger.exception("OSM pipeline failed")
        return {
            "success": False,
            "error": "OSM pipeline failed — see logs for details",
        }
