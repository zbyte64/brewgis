"""Tests for Postgres helper functions (Phase 1 of ROADMAP_5).

These tests require a running PostGIS instance.
"""

from __future__ import annotations

import pytest
from django.db import connection


pytestmark = [pytest.mark.integration]


class TestAcresFunction:
    """Tests for public.acres() — area in acres from geometry."""

    def test_acres_known_area(self):
        """100m × 100m square = 10,000 sqm / 4046.86 ≈ 2.471 acres."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT public.acres('POLYGON((0 0, 100 0, 100 100, 0 100, 0 0))'::geometry)"
            )
            result = cur.fetchone()[0]
        assert abs(result - 2.471) < 0.001, f"Expected ~2.471, got {result}"

    def test_acres_zero_area(self):
        """Point geometry should return 0 acres."""
        with connection.cursor() as cur:
            cur.execute("SELECT public.acres('POINT(0 0)'::geometry)")
            result = cur.fetchone()[0]
        assert result == 0.0


class TestSqmToAcresFunction:
    """Tests for public.sqm_to_acres() — convert sq meters to acres."""

    def test_sqm_to_acres_known(self):
        """10,000 sqm = 2.471 acres."""
        with connection.cursor() as cur:
            cur.execute("SELECT public.sqm_to_acres(10000.0)")
            result = cur.fetchone()[0]
        assert abs(result - 2.471) < 0.001, f"Expected ~2.471, got {result}"

    def test_sqm_to_acres_zero(self):
        with connection.cursor() as cur:
            cur.execute("SELECT public.sqm_to_acres(0.0)")
            assert cur.fetchone()[0] == 0.0

    def test_sqm_to_acres_negative(self):
        with connection.cursor() as cur:
            cur.execute("SELECT public.sqm_to_acres(-1000.0)")
            assert cur.fetchone()[0] == -1000.0 / 4046.86


class TestIntersectionAcresFunction:
    """Tests for public.intersection_acres()."""

    def test_intersection_acres_overlap(self):
        """Two 100m squares overlapping by 50m = 5000 sqm / 4046.86 ≈ 1.2355 acres."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT public.intersection_acres("
                "'POLYGON((0 0, 100 0, 100 100, 0 100, 0 0))'::geometry, "
                "'POLYGON((50 0, 150 0, 150 100, 50 100, 50 0))'::geometry)"
            )
            result = cur.fetchone()[0]
        assert abs(result - 1.2355) < 0.001, f"Expected ~1.2355, got {result}"

    def test_intersection_acres_disjoint(self):
        """Disjoint polygons should return 0.0 (not null)."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT public.intersection_acres("
                "'POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))'::geometry, "
                "'POLYGON((100 100, 200 100, 200 200, 100 200, 100 100))'::geometry)"
            )
            assert cur.fetchone()[0] == 0.0

    def test_intersection_acres_null_first(self):
        """Null first argument should return 0.0."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT public.intersection_acres("
                "NULL::geometry, "
                "'POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))'::geometry)"
            )
            assert cur.fetchone()[0] == 0.0


class TestClampFunction:
    """Tests for public.clamp_non_negative()."""

    def test_clamp_negative(self):
        """Negative input should return 0.0."""
        with connection.cursor() as cur:
            cur.execute("SELECT public.clamp_non_negative(-5.0)")
            assert cur.fetchone()[0] == 0.0

    def test_clamp_positive(self):
        """Positive input should return unchanged."""
        with connection.cursor() as cur:
            cur.execute("SELECT public.clamp_non_negative(3.5)")
            assert cur.fetchone()[0] == 3.5

    def test_clamp_zero(self):
        """Zero input should return 0.0."""
        with connection.cursor() as cur:
            cur.execute("SELECT public.clamp_non_negative(0.0)")
            assert cur.fetchone()[0] == 0.0
