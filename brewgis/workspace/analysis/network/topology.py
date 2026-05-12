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

from django.conf import settings
from sqlalchemy import create_engine
from sqlalchemy import text

logger = logging.getLogger(__name__)


class TopologyError(Exception):
    """Raised when topology building fails."""


def _get_db_url() -> str:
    """Return the DATABASE_URL from Django settings."""
    db_url = getattr(settings, "DATABASE_URL", None)
    if db_url:
        return db_url
    from django.conf import settings as dj_settings  # noqa: PLC0415

    db_conf = dj_settings.DATABASES["default"]
    return (
        f"postgresql://{db_conf['USER']}:{db_conf['PASSWORD']}"
        f"@{db_conf['HOST']}:{db_conf['PORT']}/{db_conf['NAME']}"
    )


class NetworkTopology:
    """Build and verify pgRouting topology on network edges/nodes."""

    def __init__(self) -> None:
        self._engine: Any = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_engine(_get_db_url())
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
                # Ensure pgRouting extension exists
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgrouting"))

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

                sql = text(
                    f"SELECT pgr_createTopology("
                    f"  '{schema}.{edge_table}', "
                    f"  {tolerance}, "
                    f"  'geom', 'id', 'source', 'target'"
                    f")"
                )
                conn.execute(sql)

                # Analyze graph for stats
                analyze_sql = text(
                    f"SELECT pgr_analyzeGraph("
                    f"  '{schema}.{edge_table}', "
                    f"  {tolerance}, "
                    f"  'geom', 'id', 'source', 'target'"
                    f")"
                )
                conn.execute(analyze_sql)

                # Get vertex count
                vertex_count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{edge_table}_vertices_pgr")
                ).scalar()

                # Get edge count with valid topology
                valid_edges = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {schema}.{edge_table} "
                        f"WHERE source IS NOT NULL AND target IS NOT NULL"
                    )
                ).scalar()

                # Get dead-end count (vertices with 1 incident edge)
                dead_ends = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {schema}.{edge_table}_vertices_pgr "
                        f"WHERE ein = 0 OR eout = 0"
                    )
                ).scalar()

                # Get gap count (vertices with 0 incident edges)
                gaps = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {schema}.{edge_table}_vertices_pgr "
                        f"WHERE ein = 0 AND eout = 0"
                    )
                ).scalar()

        except Exception as exc:
            msg = f"Failed to build pgRouting topology: {exc}"
            logger.exception(msg)
            return {"success": False, "error": msg}

        logger.info(
            "Topology built: %d vertices, %d/%d edges valid, %d dead ends, %d gaps",
            vertex_count,
            valid_edges,
            (
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {schema}.{edge_table}")
                ).scalar()
                if conn
                else 0
            ),
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
