"""Tests for the spatial allocation engine."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from brewgis.workspace.services.spatial_allocator import _compute_allocation_factors


class TestSpatialAllocation:
    """Unit tests for area-weighted spatial allocation."""

    def _make_square(self, x: float, y: float, size: float = 1.0) -> Polygon:
        """Create a square polygon at (x, y) with given size."""
        return Polygon(
            [
                (x, y),
                (x + size, y),
                (x + size, y + size),
                (x, y + size),
            ]
        )

    def test_compute_allocation_factors_simple(self) -> None:
        """A source fully overlapping a target should have weight=1."""
        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["parcel"]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        result = _compute_allocation_factors(source, target)

        assert len(result) == 1
        assert result.iloc[0]["weight"] == pytest.approx(1.0, rel=0.1)

    def test_compute_allocation_factors_half_overlap(self) -> None:
        """Half overlap should give weight=0.5."""
        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        # Target overlaps half of source
        target = gpd.GeoDataFrame(
            {"name": ["parcel"]},
            geometry=[self._make_square(5, 0, 10)],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        result = _compute_allocation_factors(source, target)

        assert len(result) == 1
        assert result.iloc[0]["weight"] == pytest.approx(0.5, rel=0.1)

    def test_compute_allocation_factors_no_overlap(self) -> None:
        """Non-overlapping geometries should raise RuntimeError."""
        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["parcel"]},
            geometry=[self._make_square(100, 100, 10)],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        with pytest.raises(RuntimeError, match="No spatial overlaps found"):
            _compute_allocation_factors(source, target)

    def test_compute_allocation_factors_multiple_targets(self) -> None:
        """Multiple targets should each get correct weights."""
        source = gpd.GeoDataFrame(
            {"val": [200]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        # Two targets covering different quarters of source
        target = gpd.GeoDataFrame(
            {"name": ["left", "right"]},
            geometry=[
                self._make_square(0, 0, 5),  # left quarter
                self._make_square(5, 0, 5),  # right quarter
            ],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        result = _compute_allocation_factors(source, target)

        assert len(result) == 2
        weights = sorted(result["weight"].tolist())
        assert weights[0] == pytest.approx(0.25, rel=0.1)
        assert weights[1] == pytest.approx(0.25, rel=0.1)

    def test_compute_allocation_factors_different_crs(self) -> None:
        """Different CRS should be handled (both converted to projected)."""
        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["parcel"]},
            geometry=[self._make_square(0, 0, 10)],
        )
        target["__tid__"] = target.index

        result = _compute_allocation_factors(source, target)

        assert len(result) == 1

    def test_allocate_value_correctness(self) -> None:
        """Allocated values should be correctly proportioned."""
        source = gpd.GeoDataFrame(
            {"pop": [1000]},
            geometry=[self._make_square(0, 0, 10)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[self._make_square(0, 0, 5)],  # 25% of source
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        allocation = _compute_allocation_factors(source, target)

        # Compute expected value
        weight = allocation.iloc[0]["weight"]
        expected = 1000.0 * weight

        # With 25% area overlap, weight ≈ 0.25
        assert expected == pytest.approx(250.0, rel=0.2)


class TestSpatialAllocationEdgeCases:
    """Edge case tests for spatial allocation."""

    def test_zero_area_source(self) -> None:
        """A source feature with zero area should raise error."""
        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[Polygon()],  # empty geometry
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        with pytest.raises(RuntimeError, match="No spatial overlaps found"):
            _compute_allocation_factors(source, target)

    def test_point_geometries(self) -> None:
        """Point geometries should produce no overlaps (area = 0)."""
        from shapely.geometry import Point

        source = gpd.GeoDataFrame(
            {"val": [100]},
            geometry=[Point(0, 0)],
            crs="EPSG:4326",
        )
        source["__sid__"] = source.index

        target = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[Point(1, 1)],
            crs="EPSG:4326",
        )
        target["__tid__"] = target.index

        with pytest.raises(RuntimeError, match="No spatial overlaps found"):
            _compute_allocation_factors(source, target)
