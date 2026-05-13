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
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

# Default network type for transport analysis
_DEFAULT_NETWORK_TYPE = "drive"

# Columns that must exist on network_edges for pgRouting topology
_REQUIRED_EDGE_COLS = {"id", "source", "target", "length", "geom"}


class NetworkExtractionError(Exception):
    """Raised when network extraction fails."""





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
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = get_engine()
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

        # Set a reasonable timeout for OSM Overpass API calls to prevent
        # hanging indefinitely when OSM is slow or unreachable.
        _saved_timeout = getattr(ox.settings, "requests_timeout", None)
        ox.settings.requests_timeout = 120
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
        finally:
            if _saved_timeout is not None:
                ox.settings.requests_timeout = _saved_timeout

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
        edges_out = edges_out.set_geometry("geom")
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
        nodes_out = nodes_out.set_geometry("geom")
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

            edges_out.to_postgis(
                edge_table,
                self.engine,
                schema=schema,
                if_exists="replace",
                index=False,
            )

            nodes_out.to_postgis(
                node_table,
                self.engine,
                schema=schema,
                if_exists="replace",
                index=False,
            )

            # Add primary keys and geometry columns
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE {schema}.{edge_table} ADD PRIMARY KEY (id)")
                )
                conn.execute(
                    text(f"ALTER TABLE {schema}.{node_table} ADD PRIMARY KEY (id)")
                )

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
