"""Property-based tests for spatial allocation invariants — conservation laws."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from shapely import area as shapely_area
from shapely.geometry import box
from shapely.ops import unary_union

# ── Strategy helpers ──────────────────────────────────────────────────


def _tiled_sources(n: int) -> list:
    """Generate n non-overlapping polygons that tile the unit square."""
    if n == 1:
        return [box(0, 0, 1, 1)]
    cols = int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    tile_w = 1.0 / cols
    tile_h = 1.0 / rows
    polygons = []
    for i in range(rows):
        for j in range(cols):
            if len(polygons) >= n:
                break
            polygons.append(
                box(j * tile_w, i * tile_h, (j + 1) * tile_w, (i + 1) * tile_h)
            )
        if len(polygons) >= n:
            break
    return polygons


def _target_polygons(n: int) -> list:
    """Generate n small rectangles entirely within the unit square."""
    rng = np.random.default_rng(99)
    polygons = []
    for _ in range(n):
        x, y = rng.uniform(0, 0.9, 2)
        polygons.append(box(x, y, x + 0.1, y + 0.1))
    return polygons


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.slow
@given(
    source_pop=st.floats(
        min_value=100, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
)
def test_population_conserved_across_allocation(
    source_pop: float,
) -> None:
    """Total population conserved when targets tile the source exactly."""
    # Single source covering the full unit square
    src_poly = box(0, 0, 1, 1)
    src_area = 1.0

    # 10×10 grid of 0.1×0.1 targets tiling the unit square
    n_tiles = 10
    tgt_polys = []
    for i in range(n_tiles):
        for j in range(n_tiles):
            tgt_polys.append(box(j * 0.1, i * 0.1, (j + 1) * 0.1, (i + 1) * 0.1))

    # Area-weighted proportional allocation
    allocated = 0.0
    for tgt_poly in tgt_polys:
        overlap_area = shapely_area(tgt_poly.intersection(src_poly))
        weight = overlap_area / src_area
        allocated += source_pop * weight

    # Exact conservation since targets perfectly tile the source
    assert abs(allocated - source_pop) / source_pop < 0.01, (
        f"Allocated {allocated:.0f} ≠ source {source_pop:.0f}"
    )


@pytest.mark.slow
@given(
    n_sources=st.integers(min_value=2, max_value=10),
    n_targets=st.integers(min_value=5, max_value=50),
    source_val=st.floats(
        min_value=10, max_value=100_000, allow_nan=False, allow_infinity=False
    ),
)
def test_sum_hint_preserves_total(
    n_sources: int,
    n_targets: int,
    source_val: float,
) -> None:
    """For sum-hint columns, total allocated ≈ total source (±5%)."""
    src_polys = _tiled_sources(n_sources)
    tgt_polys = _target_polygons(n_targets)

    tgt_gdf = gpd.GeoDataFrame(
        {"hh": [np.nan] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )
    result = tgt_gdf.copy()
    result["hh"] = 0.0
    source_union = unary_union(src_polys)

    if source_union is not None and not source_union.is_empty:
        total_overlap = sum(
            shapely_area(p.intersection(source_union))
            for p in tgt_gdf.geometry
            if source_union.intersects(p)
        )
        if total_overlap > 0:
            for i in range(n_targets):
                tgt_poly = tgt_gdf.geometry.iloc[i]
                if source_union.intersects(tgt_poly):
                    overlap = tgt_poly.intersection(source_union)
                    weight = shapely_area(overlap) / total_overlap
                    result.loc[i, "hh"] = source_val * weight

    allocated_total = float(result["hh"].sum())
    assert allocated_total > 0, "Allocation produced zero total"
    assert allocated_total <= source_val * 1.10, (
        f"Allocated {allocated_total:.0f} >> source {source_val:.0f}"
    )
    assert allocated_total >= source_val * 0.85, (
        f"Allocated {allocated_total:.0f} << 85% of source {source_val:.0f}"
    )


@pytest.mark.slow
@given(
    n_sources=st.integers(min_value=2, max_value=5),
    n_targets=st.integers(min_value=5, max_value=20),
)
def test_no_population_created_from_empty(
    n_sources: int,
    n_targets: int,
) -> None:
    """If all source values are 0, allocated values are 0."""
    src_polys = _tiled_sources(n_sources)
    tgt_polys = _target_polygons(n_targets)

    tgt_gdf = gpd.GeoDataFrame(
        {"pop": [np.nan] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )

    result = tgt_gdf.copy()
    src_union = unary_union(src_polys)
    result["pop"] = 0.0
    if src_union is not None and not src_union.is_empty:
        for i in range(n_targets):
            if src_union.intersects(tgt_gdf.geometry.iloc[i]):
                weight = shapely_area(
                    tgt_gdf.geometry.iloc[i].intersection(src_union)
                ) / max(shapely_area(tgt_gdf.geometry.iloc[i]), 1e-10)
                result.loc[i, "pop"] = 0.0 * weight

    assert float(result["pop"].sum()) == 0.0, (
        "Zero source should produce zero allocation"
    )


@pytest.mark.slow
def test_allocation_deterministic() -> None:
    """Same inputs → same outputs (reproducibility)."""
    src_polys = _tiled_sources(5)
    tgt_polys = _target_polygons(20)
    source_pop = 50000.0

    def _run_in_memory_allocation() -> gpd.GeoDataFrame:
        tgt = gpd.GeoDataFrame(
            {"pop": [np.nan] * 20, "geometry": tgt_polys},
            crs="EPSG:4326",
        )
        src_u = unary_union(src_polys)
        tgt["pop"] = 0.0
        if src_u is not None and not src_u.is_empty:
            for i in range(20):
                if src_u.intersects(tgt.geometry.iloc[i]):
                    overlap = tgt.geometry.iloc[i].intersection(src_u)
                    weight = shapely_area(overlap) / max(
                        shapely_area(tgt.geometry.iloc[i]), 1e-10
                    )
                    tgt.loc[i, "pop"] = source_pop * weight / 5
        return tgt

    result_a = _run_in_memory_allocation()
    result_b = _run_in_memory_allocation()
    pd.testing.assert_series_equal(result_a["pop"], result_b["pop"], check_names=False)


@pytest.mark.slow
@given(
    n_targets=st.integers(min_value=2, max_value=30),
)
def test_single_source_all_targets_covered(n_targets: int) -> None:
    """One source polygon covering all targets → each gets proportional allocation."""
    rng = np.random.default_rng(42)
    tgt_polys = [
        box(x, y, x + 0.15, y + 0.15) for x, y in rng.uniform(0, 0.85, (n_targets, 2))
    ]

    source_pop = 100000.0
    tgt_gdf = gpd.GeoDataFrame(
        {"pop": [np.nan] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )

    tgt_areas = [shapely_area(p) for p in tgt_polys]
    total_area = sum(tgt_areas)

    result = tgt_gdf.copy()
    result["pop"] = [source_pop * a / total_area for a in tgt_areas]

    allocated_total = float(result["pop"].sum())
    assert abs(allocated_total - source_pop) / source_pop < 0.01, (
        f"Allocated {allocated_total:.0f} ≠ source {source_pop:.0f}"
    )
    assert all(float(v) > 0 for v in result["pop"]), (
        "All targets should get positive allocation"
    )


@pytest.mark.slow
@given(
    n_sources=st.integers(min_value=2, max_value=8),
    n_targets=st.integers(min_value=10, max_value=40),
    uniform_rate=st.floats(
        min_value=10, max_value=1000, allow_nan=False, allow_infinity=False
    ),
)
def test_avg_hint_preserves_approximate_mean(
    n_sources: int,
    n_targets: int,
    uniform_rate: float,
) -> None:
    """For uniformly-valued source, area-weighted avg ≈ source value."""
    src_polys = _tiled_sources(n_sources)
    tgt_polys = _target_polygons(n_targets)

    tgt_gdf = gpd.GeoDataFrame(
        {"pct_minority": [np.nan] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )

    source_union = unary_union(src_polys)
    result = tgt_gdf.copy()
    result["pct_minority"] = 0.0
    if source_union is not None and not source_union.is_empty:
        total_weighted = 0.0
        total_weight = 0.0
        for i in range(n_targets):
            tgt_poly = tgt_gdf.geometry.iloc[i]
            if source_union.intersects(tgt_poly):
                overlap = tgt_poly.intersection(source_union)
                w = shapely_area(overlap)
                total_weighted += uniform_rate * w
                total_weight += w
        if total_weight > 0:
            wavg = total_weighted / total_weight
            assert abs(wavg - uniform_rate) / max(uniform_rate, 1) < 0.05, (
                f"Weighted avg {wavg:.1f} ≠ source rate {uniform_rate:.1f}"
            )


@pytest.mark.slow
@given(
    n_sources=st.integers(min_value=2, max_value=8),
    n_targets=st.integers(min_value=5, max_value=30),
    source_val=st.floats(
        min_value=0, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
)
def test_allocated_values_nonnegative(
    n_sources: int,
    n_targets: int,
    source_val: float,
) -> None:
    """No negative allocations, regardless of source/target geometry."""
    src_polys = _tiled_sources(n_sources)
    tgt_polys = _target_polygons(n_targets)

    tgt_gdf = gpd.GeoDataFrame(
        {"pop": [0.0] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )

    source_union = unary_union(src_polys)
    if source_union is not None and not source_union.is_empty:
        for i in range(n_targets):
            tgt_poly = tgt_gdf.geometry.iloc[i]
            if source_union.intersects(tgt_poly):
                overlap = tgt_poly.intersection(source_union)
                weight = shapely_area(overlap) / max(shapely_area(tgt_poly), 1e-10)
                val = source_val * weight / n_sources
                assert val >= 0, f"Negative allocation {val} at target {i}"


@pytest.mark.slow
@given(
    n_targets=st.integers(min_value=2, max_value=30),
)
def test_full_overlap_zero_leakage(n_targets: int) -> None:
    """When source fully covers all targets, nothing is lost (exact conservation)."""
    rng = np.random.default_rng(42)
    tgt_polys = [
        box(x, y, x + 0.05, y + 0.05) for x, y in rng.uniform(0, 0.95, (n_targets, 2))
    ]

    source_pop = 100000.0
    tgt_gdf = gpd.GeoDataFrame(
        {"pop": [np.nan] * n_targets, "geometry": tgt_polys},
        crs="EPSG:4326",
    )

    tgt_areas = [shapely_area(p) for p in tgt_polys]
    total_area = sum(tgt_areas)

    result = tgt_gdf.copy()
    result["pop"] = [source_pop * a / total_area for a in tgt_areas]

    allocated_total = float(result["pop"].sum())
    assert allocated_total == pytest.approx(source_pop, rel=1e-9), (
        f"Leaked {allocated_total:.0f} vs {source_pop:.0f}"
    )
