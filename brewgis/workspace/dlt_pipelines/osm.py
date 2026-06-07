"""dlt pipeline for OSM (OpenStreetMap) intersection density.

Reads parcel geometries from a PostGIS table, downloads the OSM road
network for the study area via osmnx, computes intersection density
(intersections per square mile) per parcel, and writes to a staging
table for dbt consumption.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox
import shapely
from django.conf import settings

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

_DEFAULT_DENSITY = 12.5
_SQ_METERS_PER_SQ_MILE = 2_589_988.11
_TARGET_TABLE = "osm_intersection_density"
CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR


def _compute_jurisdiction_density(
    boundary_geom: gpd.GeoDataFrame | gpd.GeoSeries | shapely.Geometry,
) -> float:
    """Compute intersection density (intersections / sq mi) for a boundary.

    Downloads the OSM driving road network within the boundary, identifies
    intersections (nodes with street_count >= 3), and computes density
    per square mile.

    Parameters
    ----------
    boundary_geom : gpd.GeoDataFrame | gpd.GeoSeries | shapely.Geometry
        Geometry defining the study area.  Can be a GeoDataFrame/GeoSeries
        with one or more rows (will be unioned) or a single shapely geometry.

    Returns
    -------
    float
        Intersections per square mile, or ``0.0`` when no intersections found.
        Exceptions propagate to the caller — no exception is swallowed.
    """
    # osmnx expects geos to be EPSG:4326
    if isinstance(boundary_geom, gpd.GeoDataFrame | gpd.GeoSeries):
        geom = boundary_geom.to_crs("EPSG:4326").union_all().buffer(0.001)
    else:
        # Project to EPSG:4326 and buffer (osmnx needs clean geometry)
        geom = gpd.GeoSeries([boundary_geom], crs="EPSG:4326").buffer(0.001).iloc[0]
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
    if isinstance(boundary_geom, gpd.GeoDataFrame | gpd.GeoSeries):
        boundary_aea = boundary_geom.to_crs("EPSG:6933")
        area_sq_m = boundary_aea.area.sum()
    else:
        # Project to EPSG:6933 for area calculation
        area_sq_m = (
            gpd.GeoSeries([boundary_geom], crs="EPSG:4326")
            .to_crs("EPSG:6933")
            .area.iloc[0]
        )
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
    column exists), computes the parcel union per jurisdiction in PostGIS
    (avoiding expensive Python union_all), downloads the OSM driving
    network for each jurisdiction, and writes
    ``parcel_id`` + ``intersection_density`` to
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
        ``{"table_name": str, "row_count": int}``
    """
    engine = get_engine()

    # ── Read parcel_ids and jurisdictions (no geometry) ───────────
    sql = (
        f"SELECT parcel_id, geometry FROM {schema}.{parcel_table} "
        f"WHERE geometry IS NOT NULL"
    )
    parcels: gpd.GeoDataFrame = gpd.GeoDataFrame.from_postgis(
        sql, engine, geom_col="geometry"
    )

    assert not parcels.empty, f"No parcels found in {schema}.{parcel_table}"

    logger.info(
        "OSM pipeline: read %d parcels from %s.%s",
        len(parcels),
        schema,
        parcel_table,
    )

    # Check for optional jurisdiction column
    with engine.connect() as conn:
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
        # Read just jurisdiction + geometry (re-use the already-loaded
        # GeoDataFrame — the geometry was already fetched).
        sql_juris = (
            f"SELECT parcel_id, geometry, jurisdiction "
            f"FROM {schema}.{parcel_table} WHERE geometry IS NOT NULL"
        )
        parcels = gpd.GeoDataFrame.from_postgis(sql_juris, engine, geom_col="geometry")

        # Compute the unioned boundary per jurisdiction in PostGIS,
        # then compute density via osmnx for each.
        juris_density_map: dict[str, float] = {}
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT jurisdiction, "
                    f"  ST_AsBinary(ST_Union(ST_Transform(geometry, 'EPSG:4326'))) AS geom "
                    f"FROM {schema}.{parcel_table} "
                    f"WHERE geometry IS NOT NULL "
                    f"GROUP BY jurisdiction"
                )
            ).fetchall()
        for row in rows:
            juris = str(row[0])
            union_geom = shapely.from_wkb(bytes(row[1]))
            density = _compute_jurisdiction_density(union_geom)
            juris_density_map[juris] = density

        parcels["intersection_density"] = (
            parcels["jurisdiction"].map(juris_density_map).round(2)
        )
    else:
        # Global density — union all parcels in PostGIS
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    f"SELECT ST_AsBinary(ST_Union(ST_Transform(geometry, 'EPSG:4326'))) "
                    f"FROM {schema}.{parcel_table} "
                    f"WHERE geometry IS NOT NULL"
                )
            )
            row = result.fetchone()
            if row is not None and row[0] is not None:
                union_geom = shapely.from_wkb(bytes(row[0]))
            else:
                union_geom = None

        density = (
            _compute_jurisdiction_density(union_geom)
            if union_geom is not None
            else _DEFAULT_DENSITY
        )
        parcels["intersection_density"] = np.round(density, 2)

    # ── Write to staging table ────────────────────────────────────
    target_table = f"{schema}.{_TARGET_TABLE}"
    parcels[["parcel_id", "intersection_density", "geometry"]].to_postgis(
        _TARGET_TABLE,
        get_engine(),
        schema=schema,
        if_exists="replace",
        index=False,
    )

    row_count = len(parcels)

    logger.info(
        "OSM pipeline complete: %d rows written to %s",
        row_count,
        target_table,
    )

    return {
        "table_name": target_table,
        "row_count": row_count,
    }
