"""Tests for the synthetic parcel generator.

Verifies generated parcels have valid geometry, non-negative values,
and appropriate distributions of land use categories.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.synthetic_parcel_generator import (
    generate_synthetic_parcels,
)


class TestSyntheticParcelGenerator:
    """Tests for synthetic parcel generation."""

    def test_generates_correct_count(self) -> None:
        """Should generate the requested number of parcels."""
        gdf = generate_synthetic_parcels(50, seed=42)
        assert len(gdf) == 50

    def test_zero_parcels(self) -> None:
        """Zero parcels should produce an empty GeoDataFrame."""
        gdf = generate_synthetic_parcels(0, seed=42)
        assert len(gdf) == 0

    def test_valid_geometry(self) -> None:
        """All parcels should have valid Polygon geometries."""
        gdf = generate_synthetic_parcels(20, seed=42)
        assert all(gdf.geometry.is_valid)
        assert all(isinstance(geom, Polygon) for geom in gdf.geometry)

    def test_geometry_crs(self) -> None:
        """Should use EPSG:4326."""
        gdf = generate_synthetic_parcels(10, seed=42)
        assert gdf.crs is not None
        assert gdf.crs.to_string() == "EPSG:4326"

    def test_non_negative_area(self) -> None:
        """All area columns should be non-negative."""
        gdf = generate_synthetic_parcels(50, seed=42)
        area_cols = [c for c in gdf.columns if c.startswith("area_")]
        for col in area_cols:
            assert (gdf[col] >= 0).all(), f"Column '{col}' has negative values"

    def test_non_negative_demographics(self) -> None:
        """Demographic columns should be non-negative."""
        gdf = generate_synthetic_parcels(30, seed=42)
        for col in ["pop", "hh", "du", "pop_groupquarter"]:
            assert (gdf[col] >= 0).all(), f"Column '{col}' has negative values"

    def test_non_negative_employment(self) -> None:
        """Employment columns should be non-negative."""
        gdf = generate_synthetic_parcels(30, seed=42)
        emp_cols = [c for c in gdf.columns if c.startswith("emp_") or c == "emp"]
        for col in emp_cols:
            assert (gdf[col] >= 0).all(), f"Column '{col}' has negative values"

    def test_non_negative_building_area(self) -> None:
        """Building area columns should be non-negative."""
        gdf = generate_synthetic_parcels(30, seed=42)
        bldg_cols = [c for c in gdf.columns if c.startswith("bldg_")]
        for col in bldg_cols:
            assert (gdf[col] >= 0).all(), f"Column '{col}' has negative values"

    def test_land_use_categories(self) -> None:
        """land_development_category should be one of the known values."""
        gdf = generate_synthetic_parcels(100, seed=42)
        known_categories = {
            "urban",
            "suburban",
            "rural_residential",
            "commercial",
            "industrial",
            "agricultural",
            "park",
            "vacant",
        }
        actual = set(gdf["land_development_category"].unique())
        assert actual.issubset(known_categories)

    def test_reproducible_seed(self) -> None:
        """Same seed should produce identical output."""
        gdf1 = generate_synthetic_parcels(20, seed=42)
        gdf2 = generate_synthetic_parcels(20, seed=42)
        assert (gdf1["pop"] == gdf2["pop"]).all()
        assert (gdf1["area_gross"] == gdf2["area_gross"]).all()

    def test_different_seed_different_output(self) -> None:
        """Different seeds should produce different output."""
        gdf1 = generate_synthetic_parcels(20, seed=42)
        gdf2 = generate_synthetic_parcels(20, seed=99)
        # At least some values should differ
        assert not (gdf1["pop"] == gdf2["pop"]).all()

    def test_all_schema_columns_present(self) -> None:
        """Should include all base canvas schema columns."""

        gdf = generate_synthetic_parcels(10, seed=42)
        schema_cols = set(BaseCanvasSchema.COLUMN_NAMES)
        gdf_cols = set(gdf.columns)
        # id is SERIAL (auto-generated), geometry is the geometry column
        missing = schema_cols - gdf_cols - {"id", "geometry", "geography_id"}
        assert not missing, f"Missing columns: {missing}"

    def test_some_parcels_have_non_zero_values(self) -> None:
        """At least some parcels should have non-zero values in summable cols."""
        gdf = generate_synthetic_parcels(50, seed=42)
        summable = ["pop", "hh", "du", "emp", "area_gross"]
        for col in summable:
            assert (gdf[col] > 0).any(), f"Column '{col}' is all zeros"

    def test_one_parcel(self) -> None:
        """Should handle generating a single parcel."""
        gdf = generate_synthetic_parcels(1, seed=42)
        assert len(gdf) == 1
        assert gdf.geometry.is_valid.iloc[0]
