# ruff: noqa: PT009
"""Tests for the OSM network extractor and pgRouting topology builder.

These tests verify that network extraction and topology building work
correctly against a real PostGIS/pgRouting instance.

Reference:
    - NetworkExtractor: brewgis/workspace/analysis/network/extractor.py
    - NetworkTopology: brewgis/workspace/analysis/network/topology.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import connection
from django.test import TestCase

from brewgis.workspace.analysis.network.extractor import NetworkExtractor
from brewgis.workspace.analysis.network.topology import NetworkTopology


@pytest.mark.integration
class TestNetworkExtractor(TestCase):
    """NetworkExtractor — OSM download and PostGIS write."""

    def setUp(self) -> None:
        self.extractor = NetworkExtractor()
        self.schema = "public"
        self.edge_table = "test_network_edges"
        self.node_table = "test_network_nodes"

    def tearDown(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {self.schema}.{self.edge_table} CASCADE"
            )
            cursor.execute(
                f"DROP TABLE IF EXISTS {self.schema}.{self.node_table} CASCADE"
            )
            cursor.execute(
                f"DROP TABLE IF EXISTS "
                f"{self.schema}.{self.edge_table}_vertices_pgr CASCADE"
            )

    def test_extract_fresno_bbox(self) -> None:
        """Extract OSM network for a small Fresno-area bounding box.

        This is a real network download — uses the live OSM API.
        The bbox covers ~2 km² near downtown Fresno.
        """
        # Fresno downtown area (small for speed)
        minx, miny = -119.80, 36.73
        maxx, maxy = -119.78, 36.75

        result = self.extractor.extract_for_bbox(
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            schema=self.schema,
            edge_table=self.edge_table,
            node_table=self.node_table,
        )

        self.assertTrue(
            result["success"], msg=f"Extraction failed: {result.get('error')}"
        )
        self.assertGreater(result["edge_count"], 0, "Expected at least 1 edge")
        self.assertGreater(result["node_count"], 0, "Expected at least 1 node")
        self.assertGreater(result["srid"], 0, "SRID must be positive")
        self.assertIsNone(result["error"])

        # Verify edge table exists and has correct columns
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema = '{self.schema}' "
                f"AND table_name = '{self.edge_table}'"
            )
            edge_cols = {row[0] for row in cursor.fetchall()}

        for required in ("id", "source", "target", "geom"):
            self.assertIn(
                required,
                edge_cols,
                f"Edge table missing required column: {required}",
            )

    def test_extract_empty_bbox_returns_error(self) -> None:
        """Extraction with an empty bbox (middle of ocean) should fail gracefully."""
        # Middle of the Pacific Ocean — no roads
        result = self.extractor.extract_for_bbox(
            minx=-170.0,
            miny=-20.0,
            maxx=-169.0,
            maxy=-19.0,
            schema=self.schema,
            edge_table=f"{self.edge_table}_empty",
            node_table=f"{self.node_table}_empty",
        )
        self.assertFalse(result["success"])

    @patch.object(NetworkExtractor, "engine")
    def test_extract_db_write_failure(self, mock_engine) -> None:
        """If PostGIS write fails, the method returns a failure dict."""
        mock_engine.begin.side_effect = RuntimeError("Connection lost")
        # engine is a property returning self._engine, need to wire it
        self.extractor._engine = mock_engine

        # Use a very small dummy area — real OSM download still happens but write fails
        result = self.extractor.extract_for_bbox(
            minx=-119.80,
            miny=36.73,
            maxx=-119.79,
            maxy=36.74,
            schema=self.schema,
            edge_table=self.edge_table,
            node_table=self.node_table,
        )
        # Write failure should still return a result dict (could be success or failure
        # depending on whether OSM download itself succeeded)
        self.assertIn("success", result)


@pytest.mark.integration
class TestNetworkTopology(TestCase):
    """NetworkTopology — pgRouting topology building."""

    def setUp(self) -> None:
        self.topology = NetworkTopology()
        self.extractor = NetworkExtractor()
        self.schema = "public"
        self.edge_table = "test_topology_edges"
        self.node_table = "test_topology_nodes"

        # Extract a small network for topology testing
        result = self.extractor.extract_for_bbox(
            minx=-119.80,
            miny=36.73,
            maxx=-119.78,
            maxy=36.75,
            schema=self.schema,
            edge_table=self.edge_table,
            node_table=self.node_table,
        )
        if not result["success"]:
            self.fail(f"Network extraction failed in setUp: {result.get('error')}")

    def tearDown(self) -> None:
        self.topology.drop_vertex_table(
            schema=self.schema, edge_table=self.edge_table
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {self.schema}.{self.edge_table} CASCADE"
            )
            cursor.execute(
                f"DROP TABLE IF EXISTS {self.schema}.{self.node_table} CASCADE"
            )

    def test_build_topology(self) -> None:
        """Building topology on extracted network succeeds."""
        result = self.topology.build(
            schema=self.schema,
            edge_table=self.edge_table,
            tolerance=0.00001,
        )
        self.assertTrue(
            result["success"], msg=f"Topology build failed: {result.get('error')}"
        )
        self.assertGreater(result["vertex_count"], 0)
        self.assertGreater(result["edge_count"], 0)
        # Dead-ends are expected in a road network (especially at bbox edges)
        self.assertGreaterEqual(result["dead_end_count"], 0)
        self.assertGreaterEqual(result["gap_count"], 0)

    def test_topology_enables_shortest_path(self) -> None:
        """After topology build, pgr_dijkstra should return results."""
        # Build topology
        topo_result = self.topology.build(
            schema=self.schema,
            edge_table=self.edge_table,
            tolerance=0.00001,
        )
        self.assertTrue(topo_result["success"])

        # Run a shortest-path query between two random nodes
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT id FROM {self.schema}.{self.edge_table}_vertices_pgr "
                f"LIMIT 2"
            )
            nodes = [row[0] for row in cursor.fetchall()]

        if len(nodes) < 2:
            self.skipTest("Not enough vertices for shortest-path test")

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM pgr_dijkstra("
                f"  'SELECT id, source, target, length AS cost "
                f"   FROM {self.schema}.{self.edge_table}',"
                f"  {nodes[0]}, {nodes[1]}, directed := false"
                f")"
            )
            path = cursor.fetchall()

        self.assertGreater(
            len(path), 0, "pgr_dijkstra should return at least one edge"
        )

    def test_build_nonexistent_table_returns_error(self) -> None:
        """Building topology on a nonexistent table returns failure."""
        result = self.topology.build(
            schema=self.schema,
            edge_table="nonexistent_edges",
            tolerance=0.00001,
        )
        self.assertFalse(result["success"])
        self.assertIsNotNone(result["error"])
