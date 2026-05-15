"""Tests for the spatial allocation engine."""

from __future__ import annotations

import pytest

from brewgis.workspace.services._db import get_engine, text
from brewgis.workspace.services.spatial_allocator import allocate_attributes


@pytest.mark.django_db
class TestSpatialAllocationIntegration:
    """Integration tests for allocate_attributes using real PostGIS tables."""

    @property
    def _engine(self):
        return get_engine()

    def _create_source_table(
        self, table_name: str, values: list[tuple[float, float, float, float, float]]
    ) -> None:
        """Create a source table with geometry + value columns.

        Args:
            values: list of (x, y, size, val1, val2) tuples
        """
        engine = self._engine
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
            conn.execute(
                text(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    geom GEOMETRY(POLYGON, 4326),
                    val1 DOUBLE PRECISION,
                    val2 DOUBLE PRECISION
                )
            """)
            )
            for x, y, size, v1, v2 in values:
                conn.execute(
                    text(f"""
                        INSERT INTO {table_name} (geom, val1, val2)
                        VALUES (ST_SetSRID(ST_MakeEnvelope(:x, :y, :x2, :y2), 4326), :v1, :v2)
                    """),
                    {
                        "x": x,
                        "y": y,
                        "x2": x + size,
                        "y2": y + size,
                        "v1": v1,
                        "v2": v2,
                    },
                )

    def _create_target_table(
        self, table_name: str, geometries: list[tuple[float, float, float, float]]
    ) -> None:
        """Create a bare target table with only geometry.

        Args:
            geometries: list of (x, y, x2, y2) envelope corners
        """
        engine = self._engine
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
            conn.execute(
                text(f"""
                CREATE TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    geom GEOMETRY(POLYGON, 4326)
                )
            """)
            )
            for x1, y1, x2, y2 in geometries:
                conn.execute(
                    text(f"""
                        INSERT INTO {table_name} (geom)
                        VALUES (ST_SetSRID(ST_MakeEnvelope(:x1, :y1, :x2, :y2), 4326))
                    """),
                    {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                )

    def _read_target_value(
        self, schema: str, table: str, column: str, row_id: int
    ) -> float | None:
        engine = self._engine
        with engine.begin() as conn:
            row = conn.execute(
                text(f'SELECT "{column}" FROM "{schema}"."{table}" WHERE id = :rid'),
                {"rid": row_id},
            ).fetchone()
        return float(row[0]) if row else None

    def test_full_overlap_single_column(self) -> None:
        """Source fully covering target allocates all of source value."""
        schema = "public"
        self._create_source_table("test_alloc_src_single", [(0, 0, 10, 100.0, 200.0)])
        self._create_target_table("test_alloc_tgt_single", [(0, 0, 10, 10)])

        result = allocate_attributes(
            source_schema=schema,
            source_table="test_alloc_src_single",
            target_schema=schema,
            target_table="test_alloc_tgt_single",
            columns=["val1"],
        )

        assert result["allocated_columns"] == ["val1"]
        assert result["total_features"] >= 1
        assert not result["errors"]

        value = self._read_target_value(schema, "test_alloc_tgt_single", "val1", 1)
        # Full overlap → weight ≈ 1.0 → allocated ≈ 100
        assert value is not None
        assert value == pytest.approx(100.0, rel=0.1)

    def test_half_overlap_multiple_columns(self) -> None:
        """Half-overlapping source distributes proportionally for multiple columns."""
        schema = "public"
        self._create_source_table("test_alloc_src_half", [(0, 0, 10, 100.0, 200.0)])
        self._create_target_table("test_alloc_tgt_half", [(5, 0, 15, 10)])

        result = allocate_attributes(
            source_schema=schema,
            source_table="test_alloc_src_half",
            target_schema=schema,
            target_table="test_alloc_tgt_half",
            columns=["val1", "val2"],
        )

        assert result["allocated_columns"] == ["val1", "val2"]
        assert result["total_features"] >= 2

        v1 = self._read_target_value(schema, "test_alloc_tgt_half", "val1", 1)
        v2 = self._read_target_value(schema, "test_alloc_tgt_half", "val2", 1)
        # Half overlap → weight ≈ 0.5 → allocated ≈ 50
        assert v1 is not None
        assert v1 == pytest.approx(50.0, rel=0.2)
        # val2 = 200 → allocated ≈ 100
        assert v2 is not None
        assert v2 == pytest.approx(100.0, rel=0.2)

    def test_column_prefix_applied(self) -> None:
        """Custom column prefix is applied to output columns."""
        schema = "public"
        self._create_source_table("test_alloc_src_pre", [(0, 0, 10, 100.0, 200.0)])
        self._create_target_table("test_alloc_tgt_pre", [(0, 0, 10, 10)])

        result = allocate_attributes(
            source_schema=schema,
            source_table="test_alloc_src_pre",
            target_schema=schema,
            target_table="test_alloc_tgt_pre",
            columns=["val1"],
            target_column_prefix="alloc_",
        )

        assert result["allocated_columns"] == ["alloc_val1"]

        engine = self._engine
        with engine.begin() as conn:
            cols = conn.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'test_alloc_tgt_pre'
                    AND column_name = 'alloc_val1'
                """),
            ).fetchall()
            assert len(cols) == 1

    def test_no_spatial_overlap_sets_zero(self) -> None:
        """Non-overlapping geometries result in zero allocated values (DEFAULT 0)."""
        schema = "public"
        self._create_source_table("test_alloc_src_no", [(0, 0, 10, 100.0, 200.0)])
        self._create_target_table("test_alloc_tgt_no", [(50, 50, 60, 60)])

        result = allocate_attributes(
            source_schema=schema,
            source_table="test_alloc_src_no",
            target_schema=schema,
            target_table="test_alloc_tgt_no",
            columns=["val1"],
        )

        # No overlap → UPDATE affects zero rows → rowcount = 0
        assert result["total_features"] == 0

        value = self._read_target_value(schema, "test_alloc_tgt_no", "val1", 1)
        # DEFAULT 0
        assert value == pytest.approx(0.0)
