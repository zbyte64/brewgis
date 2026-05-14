# ruff: noqa: S608 — schema/table names cannot be SQL bind parameters
"""OD distance matrix preprocessor — network distances via pgRouting.

Reads parcel centroids from the core end-state table, snaps each to the
nearest pgRouting network node, and computes a distance matrix using
``pgr_dijkstra()`` for origin-destination pairs.

The output ``trip_distribution_inputs_{scenario_id}`` table is consumed
by the T2 ``trip_distribution`` dbt Python model, replacing the default
crow-flies Euclidean distance computation.

Convention:
    Output table: ``{target_schema}.trip_distribution_inputs_{scenario_id}``
    Columns: ``origin_parcel_id``, ``dest_parcel_id``, ``network_distance_km``

Reference:
    - pgr_dijkstra: https://docs.pgrouting.org/latest/en/pgr_dijkstra.html
"""

from __future__ import annotations

import logging
from typing import Any

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

# Maximum number of origins to process per batch (bounds memory)
_BATCH_SIZE = 500

# Default travel cost column in network edges
_COST_COLUMN = "length"



class DistanceMatrixPreprocessor:
    """Compute OD network distance matrix using pgRouting.

    Snaps parcel centroids to the nearest network node, then runs
    ``pgr_dijkstra()`` for each origin against all destinations to
    compute shortest-path distances.
    """

    def __init__(self, batch_size: int = _BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    def snap_parcels_to_nodes(
        self,
        schema: str,
        end_state_table: str,
        edge_table: str = "network_edges",
    ) -> list[dict[str, Any]]:
        """Snap parcel centroids to nearest network node via ST_ClosestPoint.

        Returns a list of dicts with ``parcel_id``, ``node_id``, ``distance_m``.
        """
        sql = text(
            f"""
            WITH parcel_centroids AS (
                SELECT
                    parcel_id,
                    ST_Centroid(geom) AS centroid
                FROM {schema}.{end_state_table}
                WHERE geom IS NOT NULL
            ),
            nearest_nodes AS (
                SELECT DISTINCT ON (pc.parcel_id)
                    pc.parcel_id,
                    n.id AS node_id,
                    ST_Distance(pc.centroid, n.geom) AS distance_m
                FROM parcel_centroids pc
                CROSS JOIN LATERAL (
                    SELECT v.id, v.geom
                    FROM {schema}.{edge_table}_vertices_pgr v
                    ORDER BY pc.centroid <-> v.geom
                    LIMIT 1
                ) n
                ORDER BY pc.parcel_id, n.id
            )
            SELECT parcel_id, node_id, distance_m
            FROM nearest_nodes
            ORDER BY parcel_id
            """
        )
        with self.engine.connect() as conn:
            result = conn.execute(sql)
            rows = [
                {"parcel_id": row[0], "node_id": row[1], "distance_m": float(row[2])}
                for row in result
            ]
        logger.info("Snapped %d parcels to nearest network node", len(rows))
        return rows

    def _compute_od_batch(
        self,
        schema: str,
        edge_table: str,
        origin_nodes: list[int],
        dest_nodes: list[int],
    ) -> list[dict[str, Any]]:
        """Compute shortest-path distances from origin to all destinations.

        Uses pgr_dijkstraCost (returns only cost, not full path) for efficiency.
        """
        ori_array = ",".join(str(n) for n in origin_nodes)
        dest_array = ",".join(str(n) for n in dest_nodes)

        sql = text(
            f"""
            SELECT
                start_vid AS origin_node,
                end_vid AS dest_node,
                agg_cost AS distance_m
            FROM pgr_dijkstraCost(
                'SELECT id, source, target, {_COST_COLUMN} AS cost
                 FROM {schema}.{edge_table}',
                ARRAY[{ori_array}],
                ARRAY[{dest_array}],
                directed := false
            )
            """
        )
        with self.engine.connect() as conn:
            result = conn.execute(sql)
            rows = [
                {
                    "origin_node": row[0],
                    "dest_node": row[1],
                    "distance_m": float(row[2]),
                }
                for row in result
            ]
        return rows

    def compute_distance_matrix(
        self,
        schema: str = "public",
        end_state_table: str = "end_state_{scenario_id}",
        edge_table: str = "network_edges",
        scenario_id: str = "default",
        output_table: str | None = None,
    ) -> dict[str, Any]:
        """Compute full OD network distance matrix.

        Args:
            schema: Target PostGIS schema.
            end_state_table: Core end-state table (may include ``{scenario_id}``).
            edge_table: Name of the network edges table.
            scenario_id: Scenario identifier for table naming.
            output_table: Override output table name. Default:
                ``{schema}.trip_distribution_inputs_{scenario_id}``.

        Returns:
            Dict with keys: success, pair_count, error.
        """
        resolved_end_state = end_state_table.replace("{scenario_id}", scenario_id)
        resolved_output = (
            output_table or f"{schema}.trip_distribution_inputs_{scenario_id}"
        )

        logger.info(
            "Computing distance matrix: %s -> %s",
            resolved_end_state,
            resolved_output,
        )

        # Step 1: Snap parcels to network nodes
        parcel_nodes = self.snap_parcels_to_nodes(
            schema=schema,
            end_state_table=resolved_end_state,
            edge_table=edge_table,
        )
        if not parcel_nodes:
            return {"success": False, "pair_count": 0, "error": "No parcels found"}

        # Build node→parcel mapping
        node_to_parcel: dict[int, int] = {}
        for pn in parcel_nodes:
            node_to_parcel[pn["node_id"]] = pn["parcel_id"]

        origin_nodes = [pn["node_id"] for pn in parcel_nodes]
        dest_nodes = origin_nodes  # symmetric OD

        # Step 2: Compute OD matrix in batches
        all_rows: list[dict[str, Any]] = []
        total_batches = max(
            1, (len(origin_nodes) + self.batch_size - 1) // self.batch_size
        )

        for i in range(0, len(origin_nodes), self.batch_size):
            batch_origins = origin_nodes[i : i + self.batch_size]
            logger.info(
                "OD batch %d/%d: %d origins x %d destinations",
                i // self.batch_size + 1,
                total_batches,
                len(batch_origins),
                len(dest_nodes),
            )
            batch_rows = self._compute_od_batch(
                schema=schema,
                edge_table=edge_table,
                origin_nodes=batch_origins,
                dest_nodes=dest_nodes,
            )
            all_rows.extend(batch_rows)

        if not all_rows:
            return {
                "success": False,
                "pair_count": 0,
                "error": "No viable OD pairs found",
            }

        # Step 3: Map nodes back to parcel IDs and convert to km
        output_rows = []
        seen_pairs: set[tuple[int, int]] = set()
        for row in all_rows:
            origin_pid = node_to_parcel.get(row["origin_node"])
            dest_pid = node_to_parcel.get(row["dest_node"])
            if origin_pid is None or dest_pid is None:
                continue
            pair = (origin_pid, dest_pid)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            output_rows.append(
                {
                    "origin_parcel_id": origin_pid,
                    "dest_parcel_id": dest_pid,
                    "network_distance_km": row["distance_m"] / 1000.0,
                }
            )

        # Step 4: Write to output table
        self._write_output_table(
            schema=schema,
            output_table=resolved_output,
            rows=output_rows,
        )

        logger.info(
            "Distance matrix written: %d OD pairs to %s",
            len(output_rows),
            resolved_output,
        )
        return {
            "success": True,
            "pair_count": len(output_rows),
            "error": None,
        }

    def _write_output_table(
        self,
        schema: str,
        output_table: str,
        rows: list[dict[str, Any]],
    ) -> None:
        """Write OD distance rows to the output table."""
        # Split table name from schema
        if "." in output_table:
            parts = output_table.split(".", 1)
            schema = parts[0]
            table = parts[1]
        else:
            table = output_table

        with self.engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE"))
            conn.execute(
                text(
                    f"CREATE TABLE {schema}.{table} ("
                    f"  origin_parcel_id INTEGER NOT NULL,"
                    f"  dest_parcel_id INTEGER NOT NULL,"
                    f"  network_distance_km DOUBLE PRECISION NOT NULL"
                    f")"
                )
            )

        # Insert in batches
        insert_sql = text(
            f"INSERT INTO {schema}.{table} "
            f"(origin_parcel_id, dest_parcel_id, network_distance_km) "
            f"VALUES (:origin_parcel_id, :dest_parcel_id, :network_distance_km)"
        )
        with self.engine.begin() as conn:
            for i in range(0, len(rows), 500):
                batch = rows[i : i + 500]
                conn.execute(insert_sql, batch)

    def drop_inputs_table(
        self,
        schema: str = "public",
        scenario_id: str = "default",
        output_table: str | None = None,
    ) -> None:
        """Drop the inputs table for scenario teardown."""
        resolved = output_table or f"{schema}.trip_distribution_inputs_{scenario_id}"
        with self.engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {resolved} CASCADE"))
        logger.info("Dropped inputs table: %s", resolved)
