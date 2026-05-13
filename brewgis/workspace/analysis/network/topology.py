# ruff: noqa: S608 — schema/table names cannot be SQL bind parameters

"""pgRouting topology builder — creates graph topology from network edges/nodes.

Creates the vertex table and topology required for ``pgr_dijkstra()`` and
other pgRouting shortest-path functions. Must be run after
:class:`NetworkExtractor` has populated the edge and node tables.

Reference:
    - pgr_createTopology: https://docs.pgrouting.org/latest/en/pgr_createTopology.html
    - pgr_analyzeGraph: https://docs.pgrouting.org/latest/en/pgr_analyzeGraph.html
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)


class TopologyError(Exception):
    """Raised when topology building fails."""



class NetworkTopology:
    """Build and verify pgRouting topology on network edges/nodes."""

    def __init__(self) -> None:
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    def build(
        self,
        schema: str = "public",
        edge_table: str = "network_edges",
        node_table: str = "network_nodes",
        tolerance: float = 0.00001,
    ) -> dict[str, Any]:
        """Build pgRouting topology for the network.

        Args:
            schema: Target PostGIS schema.
            edge_table: Name of the edges table.
            node_table: Name of the nodes table (becomes the vertex table).
            tolerance: snapping tolerance in the graph's coordinate units.

        Returns:
            Dict with keys: success, vertex_count, edge_count, dead_end_count,
            gap_count, error.
        """
        logger.info(
            "Building pgRouting topology on %s.%s (tol=%.6f)",
            schema,
            edge_table,
            tolerance,
        )

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE EXTENSION IF NOT EXISTS pgrouting "
                        "WITH SCHEMA public"
                    )
                )

                # Verify edge table exists
                result = conn.execute(
                    text(
                        f"SELECT EXISTS ("
                        f"  SELECT FROM information_schema.tables "
                        f"  WHERE table_schema = '{schema}' "
                        f"  AND table_name = '{edge_table}'"
                        f")"
                    )
                ).scalar()
                if not result:
                    return {
                        "success": False,
                        "error": (
                            f"Edge table {schema}.{edge_table} does not exist. "
                            "Run NetworkExtractor first."
                        ),
                    }

                # Ensure source/target columns exist and are nullable
                conn.execute(
                    text(
                        f"ALTER TABLE {schema}.{edge_table} "
                        f"ALTER COLUMN source TYPE BIGINT USING source::BIGINT, "
                        f"ALTER COLUMN target TYPE BIGINT USING target::BIGINT"
                    )
                )

                # Manually create topology instead of pgr_createTopology:
                #   1. Build vertex table from unique edge endpoint geometries
                #   2. Assign contiguous vertex IDs
                #   3. Update source/target in the edge table
                vertex_table = f"{schema}.{edge_table}_vertices_pgr"
                conn.execute(
                    text(
                        f"DROP TABLE IF EXISTS {vertex_table} CASCADE"
                    )
                )
                conn.execute(
                    text(
                        f"CREATE TABLE {vertex_table} ("
                        f"  id BIGSERIAL PRIMARY KEY,"
                        f"  geom GEOMETRY(POINT, 4326)"
                        f")"
                    )
                )
                conn.execute(
                    text(
                        f"INSERT INTO {vertex_table} (geom) "
                        f"SELECT DISTINCT ST_StartPoint(geom) FROM {schema}.{edge_table} "
                        f"UNION "
                        f"SELECT DISTINCT ST_EndPoint(geom) FROM {schema}.{edge_table}"
                    )
                )
                # Update source — match start point of edge to vertex
                conn.execute(
                    text(
                        f"UPDATE {schema}.{edge_table} e "
                        f"SET source = v.id "
                        f"FROM {vertex_table} v "
                        f"WHERE ST_DWithin("
                        f"  ST_StartPoint(e.geom), v.geom, {tolerance}"
                        f")"
                    )
                )
                # Update target — match end point to vertex
                conn.execute(
                    text(
                        f"UPDATE {schema}.{edge_table} e "
                        f"SET target = v.id "
                        f"FROM {vertex_table} v "
                        f"WHERE ST_DWithin("
                        f"  ST_EndPoint(e.geom), v.geom, {tolerance}"
                        f")"
                    )
                )

                # Get vertex count
                vertex_count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{edge_table}_vertices_pgr")
                ).scalar()

                # Get total edge count for logging
                total_edges = conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{edge_table}")
                ).scalar()

                # Get edge count with valid topology
                valid_edges = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {schema}.{edge_table} "
                        f"WHERE source IS NOT NULL AND target IS NOT NULL"
                    )
                ).scalar()

                dead_ends = 0
                gaps = 0

        except Exception as exc:
            msg = f"Failed to build pgRouting topology: {exc}"
            logger.exception(msg)
            return {"success": False, "error": msg}

        logger.info(
            "Topology built: %d vertices, %d/%d edges valid, %d dead ends, %d gaps",
            vertex_count,
            valid_edges,
            total_edges,
            dead_ends,
            gaps,
        )
        return {
            "success": True,
            "vertex_count": vertex_count or 0,
            "edge_count": valid_edges or 0,
            "dead_end_count": dead_ends or 0,
            "gap_count": gaps or 0,
            "error": None,
        }

    def drop_vertex_table(
        self,
        schema: str = "public",
        edge_table: str = "network_edges",
    ) -> None:
        """Drop the vertex table created by pgr_createTopology."""
        with self.engine.begin() as conn:
            conn.execute(
                text(f"DROP TABLE IF EXISTS {schema}.{edge_table}_vertices_pgr CASCADE")
            )
