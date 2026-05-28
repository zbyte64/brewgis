# ruff: noqa: S608, PT009
"""Tests for the OD distance matrix preprocessor.

Verifies that pgRouting-based distance computation produces valid results:
- Positive distances
- Network distance ≥ Euclidean distance for all OD pairs
- Triangle inequality holds
- Conservations and invariants match expected properties

Reference:
    - DistanceMatrixPreprocessor: brewgis/workspace/analysis/transport/preprocessors/distance_matrix.py
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test import TransactionTestCase

from brewgis.workspace.analysis.network.extractor import NetworkExtractor
from brewgis.workspace.analysis.network.topology import NetworkTopology
from brewgis.workspace.analysis.transport.preprocessors.distance_matrix import (
    DistanceMatrixPreprocessor,
)


@pytest.mark.integration
class TestDistanceMatrixPreprocessor(TransactionTestCase):
    """DistanceMatrixPreprocessor — pgRouting OD matrix computation."""

    SCHEMA = "public"

    @classmethod
    def setUpClass(cls) -> None:
        """Extract a network once for all tests (expensive)."""
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")

        cls.edge_table = "test_dm_edges"
        cls.node_table = "test_dm_nodes"

        extractor = NetworkExtractor()
        result = extractor.extract_for_bbox(
            minx=-119.80,
            miny=36.73,
            maxx=-119.78,
            maxy=36.75,
            schema=cls.SCHEMA,
            edge_table=cls.edge_table,
            node_table=cls.node_table,
        )
        if not result["success"]:
            raise RuntimeError(
                f"Network extraction failed in setUpClass: {result.get('error')}"
            )

        topology = NetworkTopology()
        topo_result = topology.build(
            schema=cls.SCHEMA,
            edge_table=cls.edge_table,
            tolerance=0.00001,
        )
        if not topo_result["success"]:
            raise RuntimeError(
                f"Topology build failed in setUpClass: {topo_result.get('error')}"
            )

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up network tables."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {cls.SCHEMA}.{cls.edge_table}_vertices_pgr CASCADE"
            )
            cursor.execute(
                f"DROP TABLE IF EXISTS {cls.SCHEMA}.{cls.edge_table} CASCADE"
            )
            cursor.execute(
                f"DROP TABLE IF EXISTS {cls.SCHEMA}.{cls.node_table} CASCADE"
            )
        super().tearDownClass()

    def setUp(self) -> None:
        self.preprocessor = DistanceMatrixPreprocessor(batch_size=100)
        self.end_state_table = "test_dm_end_state"
        self.output_table = f"{self.SCHEMA}.test_dm_output"

        # Create a synthetic end-state table with known centroids
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS "
                f"{self.SCHEMA}.{self.end_state_table} ("
                f"  parcel_id INTEGER PRIMARY KEY,"
                f"  geom GEOMETRY(POINT, 4326)"
                f")"
            )
            # Insert 5 test parcels in a grid pattern near Fresno
            test_parcels = [
                (1, -119.795, 36.740),
                (2, -119.793, 36.740),
                (3, -119.795, 36.738),
                (4, -119.791, 36.739),
                (5, -119.793, 36.738),
            ]
            for pid, lon, lat in test_parcels:
                cursor.execute(
                    f"INSERT INTO {self.SCHEMA}.{self.end_state_table} "
                    f"(parcel_id, geom) VALUES (%s, "
                    f"ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    [pid, lon, lat],
                )

    def tearDown(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {self.SCHEMA}.{self.end_state_table} CASCADE"
            )
            cursor.execute(f"DROP TABLE IF EXISTS {self.output_table} CASCADE")

    def _get_network_distances(self) -> list[dict]:
        """Fetch computed distance matrix from output table."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT origin_parcel_id, dest_parcel_id, network_distance_km "
                f"FROM {self.output_table} ORDER BY origin_parcel_id, dest_parcel_id"
            )
            return [
                {"origin": r[0], "dest": r[1], "distance_km": r[2]}
                for r in cursor.fetchall()
            ]

    def _get_euclidean_distance_km(self, pid1: int, pid2: int) -> float | None:
        """Compute Euclidean distance between two test parcels."""
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT ST_Distance(a.geom, b.geom) * 111.32 "
                f"FROM {self.SCHEMA}.{self.end_state_table} a, "
                f"{self.SCHEMA}.{self.end_state_table} b "
                f"WHERE a.parcel_id = %s AND b.parcel_id = %s",
                [pid1, pid2],
            )
            row = cursor.fetchone()
            return float(row[0]) if row else None

    def test_compute_distance_matrix_succeeds(self) -> None:
        """Distance matrix computation returns success with results."""
        result = self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        self.assertTrue(result["success"], msg=f"Failed: {result.get('error')}")
        self.assertGreater(result["pair_count"], 0)

    def test_all_distances_positive(self) -> None:
        """All network distances must be positive (> 0)."""
        self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        distances = self._get_network_distances()
        for d in distances:
            self.assertGreater(
                d["distance_km"],
                0,
                f"Distance from parcel {d['origin']} to {d['dest']} must be positive",
            )

    def test_zero_distance_self_to_self(self) -> None:
        """Distance from a parcel to itself should be 0 km (intra-zonal)."""
        self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        distances = self._get_network_distances()
        for d in distances:
            if d["origin"] == d["dest"]:
                self.assertAlmostEqual(
                    d["distance_km"],
                    0.0,
                    delta=0.001,
                    msg=f"Self-pair ({d['origin']}, {d['dest']}) should be 0 km",
                )

    def test_network_distance_ge_euclidean(self) -> None:
        """Network distance should be ≥ Euclidean distance (circuity ≥ 1.0).

        This is a fundamental invariant of road networks — paths are at
        least as long as straight-line distances.
        """
        self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        distances = self._get_network_distances()
        for d in distances:
            if d["origin"] == d["dest"]:
                continue  # skip self-pairs
            euclidean = self._get_euclidean_distance_km(d["origin"], d["dest"])
            if euclidean is not None and euclidean > 0:
                self.assertGreaterEqual(
                    d["distance_km"],
                    euclidean * 0.99,  # allow 1% numerical tolerance
                    msg=(
                        f"Network distance {d['distance_km']:.4f} km < "
                        f"Euclidean {euclidean:.4f} km for pair "
                        f"({d['origin']}, {d['dest']})"
                    ),
                )

    def test_triangle_inequality(self) -> None:
        """Network distances should approximately satisfy triangle inequality.

        d(A, C) ≤ d(A, B) + d(B, C) with numerical tolerance for
        floating point and pgRouting rounding.
        """
        self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        distances = self._get_network_distances()

        # Build lookup: (origin, dest) → distance_km
        lookup: dict[tuple[int, int], float] = {}
        for d in distances:
            lookup[(d["origin"], d["dest"])] = d["distance_km"]

        parcels = {d["origin"] for d in distances}
        for a in parcels:
            for b in parcels:
                for c in parcels:
                    if a == b or b == c or a == c:
                        continue
                    ab = lookup.get((a, b))
                    bc = lookup.get((b, c))
                    ac = lookup.get((a, c))
                    if ab is not None and bc is not None and ac is not None:
                        self.assertLessEqual(
                            ac,
                            ab + bc + 0.1,  # 100m tolerance
                            msg=(
                                f"Triangle inequality violated: "
                                f"d({a},{c})={ac:.4f} > "
                                f"d({a},{b})={ab:.4f} + d({b},{c})={bc:.4f}"
                            ),
                        )

    def test_distance_matrix_symmetric(self) -> None:
        """Undirected graph should produce symmetric distances.

        d(A, B) ≈ d(B, A) within numerical tolerance.
        """
        self.preprocessor.compute_distance_matrix(
            schema=self.SCHEMA,
            end_state_table=self.end_state_table,
            edge_table=self.edge_table,
            scenario_id="test",
            output_table=self.output_table,
        )
        distances = self._get_network_distances()

        lookup: dict[tuple[int, int], float] = {}
        for d in distances:
            lookup[(d["origin"], d["dest"])] = d["distance_km"]

        for d in distances:
            if d["origin"] == d["dest"]:
                continue
            reverse = lookup.get((d["dest"], d["origin"]))
            if reverse is not None:
                self.assertAlmostEqual(
                    d["distance_km"],
                    reverse,
                    delta=0.01,
                    msg=(
                        f"Asymmetry: d({d['origin']},{d['dest']})="
                        f"{d['distance_km']:.4f} ≠ "
                        f"d({d['dest']},{d['origin']})={reverse:.4f}"
                    ),
                )

    def test_no_parcels_returns_error(self) -> None:
        """Empty parcel table should return a failure."""
        empty_table = "test_dm_empty"
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE TABLE {self.SCHEMA}.{empty_table} ("
                f"  parcel_id INTEGER PRIMARY KEY,"
                f"  geom GEOMETRY(POINT, 4326)"
                f")"
            )

        try:
            result = self.preprocessor.compute_distance_matrix(
                schema=self.SCHEMA,
                end_state_table=empty_table,
                edge_table=self.edge_table,
                scenario_id="test",
                output_table=f"{self.SCHEMA}.test_dm_empty_output",
            )
            self.assertFalse(result["success"])
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DROP TABLE IF EXISTS {self.SCHEMA}.{empty_table} CASCADE"
                )
                cursor.execute(
                    f"DROP TABLE IF EXISTS {self.SCHEMA}.test_dm_empty_output CASCADE"
                )
