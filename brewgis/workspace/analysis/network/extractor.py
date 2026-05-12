"""OSM network extractor — downloads road network via osmnx and writes to PostGIS.

Creates ``network_edges`` and ``network_nodes`` tables in the target schema
using the projected coordinate system of the downloaded graph. Both tables
include the geometry columns needed for pgRouting topology.

This module is an *external preprocessor* — it runs outside dbt and creates
tables that dbt models reference via ``source()`` or ``ref()``.

Reference:
    - osmnx: https://osmnx.readthedocs.io/
    - pgRouting: https://docs.pgrouting.org/
"""

from __future__ import annotations

import logging
from typing import Any

import osmnx as ox
from django.conf import settings
from sqlalchemy import create_engine
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Default network type for transport analysis
_DEFAULT_NETWORK_TYPE = "drive"

# Columns that must exist on network_edges for pgRouting topology
_REQUIRED_EDGE_COLS = {"id", "source", "target", "length", "geom"}


class NetworkExtractionError(Exception):
    """Raised when network extraction fails."""


def _get_db_url() -> str:
    """Return the DATABASE_URL from Django settings."""
    db_url = getattr(settings, "DATABASE_URL", None)
    if db_url:
        return db_url

    # Fall back to building from DATABASES
    from django.conf import settings as dj_settings  # noqa: PLC0415

    db_conf = dj_settings.DATABASES["default"]
    return (
        f"postgresql://{db_conf['USER']}:{db_conf['PASSWORD']}"
        f"@{db_conf['HOST']}:{db_conf['PORT']}/{db_conf['NAME']}"
    )


def _ensure_geometry_columns(
    conn: Any,
    schema: str,
    edge_table: str,
    node_table: str,
    srid: int,
) -> None:
    """Ensure geometry columns have PostGIS type registration for pgRouting."""
    conn.execute(
        text(
            f"SELECT public.ST_AddGeometryColumn("
            f"'{schema}', '{edge_table}', 'geom', {srid}, 'LINESTRING', 2)"
        )
    )
    conn.execute(
        text(
            f"SELECT public.ST_AddGeometryColumn("
            f"'{schema}', '{node_table}', 'geom', {srid}, 'POINT', 2)"
        )
    )
    conn.commit()


class NetworkExtractor:
    """Download OSM road network and write to PostGIS.

    The extractor downloads a drivable road network for a given bounding
    box, projects it to the local UTM zone, and writes edge and node
    tables suitable for pgRouting topology.
    """

    def __init__(self, network_type: str = _DEFAULT_NETWORK_TYPE) -> None:
        self.network_type = network_type
        self._engine: Any = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(_get_db_url())
        return self._engine

    def extract_for_bbox(
        self,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        schema: str = "public",
        edge_table: str = "network_edges",
        node_table: str = "network_nodes",
        retain_tmp_tables: bool = False,
    ) -> dict[str, Any]:
        """Download OSM network for a bounding box and write to PostGIS.

        Args:
            minx: Minimum longitude (WGS84).
            miny: Minimum latitude (WGS84).
            maxx: Maximum longitude (WGS84).
            maxy: Maximum latitude (WGS84).
            schema: Target PostGIS schema.
            edge_table: Name for the edges table.
            node_table: Name for the nodes table.
            retain_tmp_tables: If True, keep intermediate tables for debugging.

        Returns:
            Dict with keys: success, edge_count, node_count, srid, error.
        """
        bbox = (minx, miny, maxx, maxy)
        logger.info(
            "Downloading OSM %s network for bbox: %s",
            self.network_type,
            bbox,
        )

        try:
            graph = ox.graph_from_bbox(
                bbox=bbox,
                network_type=self.network_type,
                retain_all=True,
                truncate_by_edge=True,
            )
        except Exception as exc:
            msg = f"Failed to download OSM network: {exc}"
            logger.exception(msg)
            return {"success": False, "error": msg}

        if graph.number_of_edges() == 0:
            return {
                "success": False,
                "error": "OSM network has zero edges for the given bounding box",
            }

        # Convert to GeoDataFrames — osmnx auto-projects to UTM
        edges_gdf: Any = ox.graph_to_gdfs(graph, nodes=False, edges=True)
        nodes_gdf: Any = ox.graph_to_gdfs(graph, nodes=True, edges=False)

        # Determine SRID from the projected CRS
        srid = _crs_to_srid(edges_gdf.crs)
        logger.info(
            "Network extracted: %d edges, %d nodes, SRID=%d",
            len(edges_gdf),
            len(nodes_gdf),
            srid,
        )

        # Normalize edge columns for pgRouting
        edges_gdf = edges_gdf.reset_index()
        edges_gdf = edges_gdf.rename(
            columns={
                "u": "source",
                "v": "target",
                "key": "edge_key",
                "geometry": "geom",
            }
        )

        # Keep required columns
        edge_cols = ["source", "target", "geom"]
        if "length" in edges_gdf.columns:
            edge_cols.append("length")
        if "highway" in edges_gdf.columns:
            edge_cols.append("highway")
        edges_out = edges_gdf[edge_cols].copy()
        edges_out["id"] = range(1, len(edges_out) + 1)

        # Normalize node columns
        nodes_gdf = nodes_gdf.reset_index()
        nodes_gdf = nodes_gdf.rename(columns={"geometry": "geom"})
        node_cols = ["geom"]
        if "y" in nodes_gdf.columns:
            node_cols.append("y")
        if "x" in nodes_gdf.columns:
            node_cols.append("x")
        nodes_out = nodes_gdf[node_cols].copy()
        nodes_out["id"] = range(1, len(nodes_out) + 1)

        # Write to PostGIS
        try:
            with self.engine.begin() as conn:
                # Create schema if needed
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

                # Drop existing tables for idempotent refresh
                conn.execute(
                    text(f"DROP TABLE IF EXISTS {schema}.{edge_table} CASCADE")
                )
                conn.execute(
                    text(f"DROP TABLE IF EXISTS {schema}.{node_table} CASCADE")
                )

            edges_out.to_sql(
                edge_table,
                self.engine,
                schema=schema,
                if_exists="replace",
                index=False,
                method="multi",
            )

            nodes_out.to_sql(
                node_table,
                self.engine,
                schema=schema,
                if_exists="replace",
                index=False,
                method="multi",
            )

            # Add primary keys and geometry columns
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE {schema}.{edge_table} ADD PRIMARY KEY (id)")
                )
                conn.execute(
                    text(f"ALTER TABLE {schema}.{node_table} ADD PRIMARY KEY (id)")
                )
                _ensure_geometry_columns(conn, schema, edge_table, node_table, srid)

        except Exception as exc:
            msg = f"Failed to write network to PostGIS: {exc}"
            logger.exception(msg)
            return {"success": False, "error": msg}

        logger.info(
            "Network written to %s.%s (%d edges) and %s.%s (%d nodes)",
            schema,
            edge_table,
            len(edges_out),
            schema,
            node_table,
            len(nodes_out),
        )
        return {
            "success": True,
            "edge_count": len(edges_out),
            "node_count": len(nodes_out),
            "srid": srid,
            "error": None,
        }


def _crs_to_srid(crs: Any) -> int:
    """Extract EPSG SRID from a CRS object."""
    if crs is None:
        return 4326
    try:
        return int(crs.to_epsg())
    except Exception:
        # Fall back to WGS84
        return 4326
