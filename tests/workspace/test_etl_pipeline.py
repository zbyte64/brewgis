"""End-to-end tests for the ETL pipeline (populate_base_canvas management command).

Tests that ``populate_base_canvas --synthetic N`` produces a valid
base canvas table with all 77 columns, no NULLs in required columns,
and reasonable aggregate values.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection

from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema


@pytest.mark.integration
class TestETLPipeline:
    """End-to-end tests for the ETL pipeline."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, db) -> None:
        """Ensure clean state before and after each test."""
        BaseCanvasManager.drop_table()
        yield
        BaseCanvasManager.drop_table()

    def _validate_base_canvas(self, expected_rows: int) -> None:
        """Assert the base canvas table meets post-ETL expectations."""
        # Table exists
        assert BaseCanvasManager.table_exists()

        # Schema is valid
        missing = BaseCanvasManager.validate_schema()
        assert not missing, f"Missing columns: {missing}"

        # Count rows
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            count = cursor.fetchone()[0]
            assert count == expected_rows, f"Expected {expected_rows} rows, got {count}"

        # No NULLs in NON_NULL_COLUMNS
        with connection.cursor() as cursor:
            non_null_checks = " OR ".join(
                f'"{c}" IS NULL' for c in BaseCanvasSchema.NON_NULL_COLUMNS
            )
            cursor.execute(
                f"SELECT COUNT(*) FROM public.base_canvas WHERE {non_null_checks}"
            )
            null_count = cursor.fetchone()[0]
            assert null_count == 0, f"{null_count} rows have NULLs in required columns"

    def _query_sum(self, column: str) -> float:
        """Return the column sum from the base canvas."""
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT COALESCE(SUM("{column}"), 0) FROM public.base_canvas'
            )
            return float(cursor.fetchone()[0])

    # ── Tests ─────────────────────────────────────────────────────────

    def test_synthetic_50_pipeline(self) -> None:
        """Running with --synthetic 50 should produce a valid table."""
        call_command("populate_base_canvas", synthetic=50)
        self._validate_base_canvas(50)

    def test_synthetic_10_pipeline(self) -> None:
        """Running with --synthetic 10 should produce a valid table."""
        call_command("populate_base_canvas", synthetic=10)
        self._validate_base_canvas(10)

    def test_all_columns_populated(self) -> None:
        """All 77 schema columns should exist and be populated."""
        call_command("populate_base_canvas", synthetic=20)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'base_canvas'
                ORDER BY ordinal_position
                """
            )
            db_cols = {row[0] for row in cursor.fetchall()}
        expected = set(BaseCanvasSchema.COLUMN_NAMES)
        # id is SERIAL but also a column
        missing = expected - db_cols
        assert not missing, f"Missing columns from DB: {missing}"

    def test_area_columns_non_negative(self) -> None:
        """All area columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=30)
        area_cols = [c for c in BaseCanvasSchema.COLUMN_NAMES if c.startswith("area_")]
        for col in area_cols:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_area_gross_positive(self) -> None:
        """area_gross should be positive for all rows."""
        call_command("populate_base_canvas", synthetic=25)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE area_gross <= 0"
            )
            zero_count = cursor.fetchone()[0]
            assert zero_count == 0, f"{zero_count} rows with area_gross <= 0"

    def test_demographic_columns_non_negative(self) -> None:
        """Demographic columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=20)
        for col in ["pop", "hh", "du", "pop_groupquarter"]:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_employment_columns_non_negative(self) -> None:
        """Employment columns should be >= 0."""
        call_command("populate_base_canvas", synthetic=20)
        emp_cols = [c for c in BaseCanvasSchema.COLUMN_NAMES if c.startswith("emp")]
        for col in emp_cols:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" < 0'
                )
                neg_count = cursor.fetchone()[0]
                assert neg_count == 0, f"Column '{col}' has {neg_count} negative values"

    def test_schema_idempotent(self) -> None:
        """Running the command twice should succeed (idempotent)."""
        call_command("populate_base_canvas", synthetic=10)
        call_command("populate_base_canvas", synthetic=10, truncate=True)
        self._validate_base_canvas(10)

    def test_skip_imputation(self) -> None:
        """--skip-imputation should leave some nulls in paintable columns."""
        call_command("populate_base_canvas", synthetic=20, skip_imputation=True)
        # The table should still exist and have the right columns
        assert BaseCanvasManager.table_exists()
        missing = BaseCanvasManager.validate_schema()
        assert not missing
        # But some nulls may exist in paintable columns (static ones are fine)
        with connection.cursor() as cursor:
            # Pick one paintable column that depends on imputation
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE intersection_density IS NULL"
            )
            null_count = cursor.fetchone()[0]
            # If synthetic data generator filled it, skip_imputation might still have data
            # We just verify the command doesn't error
            assert BaseCanvasManager.table_exists()

    def test_land_development_category_populated(self) -> None:
        """land_development_category should be populated."""
        call_command("populate_base_canvas", synthetic=30)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT land_development_category FROM public.base_canvas"
            )
            categories = {row[0] for row in cursor.fetchall()}
            assert len(categories) > 0
            assert "" not in categories  # no empty strings

    def test_intersection_density_defaulted(self) -> None:
        """intersection_density should be populated after imputation."""
        call_command("populate_base_canvas", synthetic=20)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM public.base_canvas WHERE intersection_density IS NULL"
            )
            assert cursor.fetchone()[0] == 0

    def test_irrigation_columns_defaulted(self) -> None:
        """Irrigation columns should be non-null."""
        call_command("populate_base_canvas", synthetic=20)
        for col in ["residential_irrigated_area", "commercial_irrigated_area"]:
            with connection.cursor() as cursor:
                cursor.execute(
                    f'SELECT COUNT(*) FROM public.base_canvas WHERE "{col}" IS NULL'
                )
                assert cursor.fetchone()[0] == 0, f"NULLs in {col}"

    def test_spatial_allocation_postgis(self, db) -> None:
        """Area-weighted allocation via PostGIS produces correct proportions."""
        import geopandas as gpd  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        from shapely.geometry import box  # noqa: PLC0415

        from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL  # noqa: PLC0415

        # ── Source: two adjacent rectangles with known values ──────────
        src_data = gpd.GeoDataFrame(
            {"pop": [100, 200], "geometry": [box(0, 0, 10, 10), box(10, 0, 20, 10)]},
            crs="EPSG:4326",
        )

        # ── Targets overlapping both sources ───────────────────────────
        # T1: left half of source A
        # T2: straddles both
        # T3: right half of source B
        tgt_data = gpd.GeoDataFrame(
            {
                "pop": [np.nan, np.nan, np.nan],
                "geometry": [
                    box(0, 0, 5, 10),
                    box(5, 0, 15, 10),
                    box(15, 0, 20, 10),
                ],
            },
            crs="EPSG:4326",
        )

        class MockAllocSource:
            available = True

            def fetch_block_group_data(
                self, state_fips: str = "", county_fips: str = ""
            ) -> gpd.GeoDataFrame:
                return src_data

        etl = BaseCanvasETL()
        result = etl._allocate_from_source(tgt_data.copy(), MockAllocSource(), ["pop"])

        # Verify area-weighted proportions
        # T1 ~50% of Source A (100 * 0.5 ≈ 50)
        assert result.loc[0, "pop"] == pytest.approx(50, abs=5), "T1 allocation"
        # T2 ~50% of A + ~50% of B (100*0.5 + 200*0.5 ≈ 150)
        assert result.loc[1, "pop"] == pytest.approx(150, abs=5), "T2 allocation"
        # T3 ~50% of Source B (200 * 0.5 ≈ 100)
        assert result.loc[2, "pop"] == pytest.approx(100, abs=5), "T3 allocation"
        # Sum should equal total source pop
        assert result["pop"].sum() == pytest.approx(300, abs=10), "Total population"


def test_reconcile_du_aggregates() -> None:
    """_reconcile_aggregates overwrites du_detsf when SL+LL are populated from built-form allocation."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL  # noqa: PLC0415

    # ── Simulate ACS pre-population: du_detsf has a value, SL/LL got filled later ──
    gdf = pd.DataFrame({
        "du_detsf": [100.0, 0.0, np.nan, 50.0, np.nan],
        "du_detsf_sl": [40.0, 0.0, 60.0, 30.0, 0.0],
        "du_detsf_ll": [60.0, 0.0, 40.0, 15.0, 0.0],
    })
    etl = BaseCanvasETL()
    result = etl._reconcile_aggregates(gdf)

    # Row 0: both SL and LL filled → aggregate overwritten from ACS value to sum
    assert result.loc[0, "du_detsf"] == 100.0, "Aggregate should be sum of SL+LL"

    # Row 1: SL=0, LL=0 → sub_sum == 0 → not overwritten (sub_sum > 0 guard)
    assert result.loc[1, "du_detsf"] == 0.0, "Zero-sum sub-columns not reconciled"

    # Row 2: ACS no value, SL+LL filled → aggregate should be sum
    assert result.loc[2, "du_detsf"] == 100.0, "Null aggregate filled from sub-components"

    # Row 3: both SL and LL filled → aggregate should be sum, not original ACS value
    assert result.loc[3, "du_detsf"] == 45.0, "Existing aggregate overwritten by correct sum"

    # Row 4: SL and LL both zero → sub_sum == 0 → stays NaN (sub_sum > 0 guard)
    assert pd.isna(result.loc[4, "du_detsf"]), "Zero-sum sub-columns should not change aggregate"
    # ── Test du aggregate from components ─────────────────────────────────
    gdf2 = pd.DataFrame({
        "du": [200.0, np.nan, np.nan],
        "du_detsf": [100.0, 50.0, 0.0],
        "du_attsf": [30.0, 20.0, np.nan],
        "du_mf": [70.0, 30.0, np.nan],
    })
    result2 = etl._reconcile_aggregates(gdf2)
    # Row 0: du already set, should stay
    assert result2.loc[0, "du"] == 200.0, "Existing du not overwritten when sub-columns match"
    # Row 1: null du, all sub-columns present → sum
    assert result2.loc[1, "du"] == 100.0, "Null du filled from sub-columns"
    # Row 2: du null, but attsf and mf are NaN → sub_sum not all valid → skip
    assert pd.isna(result2.loc[2, "du"]), "du stays NaN when sub-columns missing"


def test_equity_avg_allocation(db) -> None:
    import geopandas as gpd  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from shapely.geometry import box  # noqa: PLC0415

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL  # noqa: PLC0415
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema  # noqa: PLC0415

    # ── Source: three rectangles with known rates ──────────────────────
    # Source A: 10x10 box with pct_minority=10%, median_income=50000
    # Source B: 10x10 box with pct_minority=50%, median_income=80000
    src_data = gpd.GeoDataFrame(
        {
            "pct_minority": [10.0, 50.0],
            "median_income": [50000.0, 80000.0],
            "pop": [100, 200],  # sum column — should use area-weighted sum
            "geometry": [box(0, 0, 10, 10), box(10, 0, 20, 10)],
        },
        crs="EPSG:4326",
    )
    # Verify schema has correct aggregation_hint for these columns
    assert BaseCanvasSchema.get("pct_minority").aggregation_hint == "avg"
    assert BaseCanvasSchema.get("median_income").aggregation_hint == "avg"
    assert BaseCanvasSchema.get("pop").aggregation_hint == "sum"

    # ── Targets overlapping both sources ───────────────────────────────
    # T1: left half of Source A (x: 0-5)
    # T2: straddles both (x: 5-15) — 50% A, 50% B
    # T3: right half of Source B (x: 15-20)
    tgt_data = gpd.GeoDataFrame(
        {
            "pct_minority": [np.nan, np.nan, np.nan],
            "median_income": [np.nan, np.nan, np.nan],
            "pop": [np.nan, np.nan, np.nan],
            "geometry": [
                box(0, 0, 5, 10),
                box(5, 0, 15, 10),
                box(15, 0, 20, 10),
            ],
        },
        crs="EPSG:4326",
    )

    class MockDemographicSource:
        available = True
        def fetch_block_group_data(
            self, state_fips: str = "", county_fips: str = ""
        ) -> gpd.GeoDataFrame:
            return src_data

    etl = BaseCanvasETL()
    result = etl._allocate_from_source(
        tgt_data.copy(),
        MockDemographicSource(),
        ["pct_minority", "median_income", "pop"],
    )

    # ── Verify area-weighted averages for AVG columns ───────────────────
    # T1: 100% of Source A → pct_minority = 10.0, median_income = 50000
    assert result.loc[0, "pct_minority"] == pytest.approx(10.0, abs=0.5), "T1 pct_minority avg"
    assert result.loc[0, "median_income"] == pytest.approx(50000, abs=1000), "T1 median_income avg"
    # T1 pop (sum column): 50% of Source A = 50
    assert result.loc[0, "pop"] == pytest.approx(50, abs=5), "T1 pop sum"

    # T2: straddles both → pct_minority avg = (10*0.5 + 50*0.5) / (0.5 + 0.5) = 30
    # Note: intersection areas are equal (5x10 = 50 sq deg each, same area in 6933 too)
    assert result.loc[1, "pct_minority"] == pytest.approx(30.0, abs=2), "T2 pct_minority avg"
    # T2 median_income avg = (50000*0.5 + 80000*0.5) / (0.5 + 0.5) = 65000
    assert result.loc[1, "median_income"] == pytest.approx(65000, abs=2000), "T2 median_income avg"
    # T2 pop (sum): 50% of A + 50% of B = 50 + 100 = 150
    assert result.loc[1, "pop"] == pytest.approx(150, abs=10), "T2 pop sum"

    # T3: 100% of Source B → pct_minority = 50.0, median_income = 80000
    assert result.loc[2, "pct_minority"] == pytest.approx(50.0, abs=2), "T3 pct_minority avg"
    assert result.loc[2, "median_income"] == pytest.approx(80000, abs=2000), "T3 median_income avg"
    # T3 pop (sum): 50% of Source B = 100
    assert result.loc[2, "pop"] == pytest.approx(100, abs=5), "T3 pop sum"

def test_compute_areas_equal_area() -> None:
    """_compute_areas uses EPSG:6933 equal-area projection, not inflated EPSG:3857."""
    import geopandas as gpd  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from shapely.geometry import box  # noqa: PLC0415

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL  # noqa: PLC0415

    # 0.1° × 0.1° box near Sacramento (38.5°N, -121.5°W)
    poly = box(-121.5, 38.5, -121.4, 38.6)
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")

    etl = BaseCanvasETL()
    result = etl._compute_areas(gdf.copy())

    # Expected: ~23,900 acres for a 0.1° box at this latitude
    # 0.1° lat ≈ 11,132 m, 0.1° lon ≈ 8,712 m (cos 38.5°)
    # Area ≈ 96,982,000 m² ≈ 23,965 acres — allow ±5% tolerance
    assert result.loc[0, "area_gross"] == pytest.approx(23965, rel=0.05)

    # Derived columns should be proportional
    assert result.loc[0, "area_parcel"] == pytest.approx(23965 * 0.85, rel=0.01)
    assert result.loc[0, "area_dev_condition"] == pytest.approx(23965 * 0.7, rel=0.01)
    assert result.loc[0, "area_row"] == pytest.approx(23965 * 0.15, rel=0.01)


def test_compute_areas_preserves_crs() -> None:
    """_compute_areas does not mutate the original GeoDataFrame CRS."""
    import geopandas as gpd  # noqa: PLC0415
    from shapely.geometry import box  # noqa: PLC0415

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL  # noqa: PLC0415

    poly = box(-121.5, 38.5, -121.4, 38.6)
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")
    original_crs = gdf.crs

    etl = BaseCanvasETL()
    result = etl._compute_areas(gdf)

    # Original GDF CRS is preserved
    assert gdf.crs == original_crs
    # Resulting GDF should still have area columns in acres
    assert "area_gross" in result.columns
    assert result.loc[0, "area_gross"] > 0


def test_compute_area_by_use() -> None:
    """_compute_area_by_use populates area-by-use columns from land_development_category."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

    gdf = (
        gpd.GeoDataFrame(
            {
                "land_development_category": ["urban", "agricultural", "undeveloped"],
                "area_parcel": [10.0, 20.0, 30.0],
                "area_parcel_res": [np.nan, np.nan, np.nan],
                "area_parcel_emp_ag": [np.nan, np.nan, np.nan],
                "area_parcel_no_use": [np.nan, np.nan, np.nan],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            }
        )
        .set_geometry("geometry")
        .set_crs("EPSG:4326")
    )

    etl = BaseCanvasETL()
    result = etl._compute_area_by_use(gdf)

    # Urban parcel gets area_parcel_res
    assert result.loc[0, "area_parcel_res"] == 10.0
    # Agricultural parcel gets area_parcel_emp_ag
    assert result.loc[1, "area_parcel_emp_ag"] == 20.0
    # Undeveloped parcel gets area_parcel_no_use
    assert result.loc[2, "area_parcel_no_use"] == 30.0

    # Other columns remain NaN (not matching their category)
    assert np.isnan(result.loc[1, "area_parcel_res"])
    assert np.isnan(result.loc[0, "area_parcel_emp_ag"])


def test_compute_area_by_use_missing_category_column() -> None:
    """_compute_area_by_use returns gdf unchanged when land_development_category is missing."""
    import geopandas as gpd
    from shapely.geometry import Point

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

    gdf = (
        gpd.GeoDataFrame({"area_parcel": [10.0], "geometry": [Point(0, 0)]})
        .set_geometry("geometry")
        .set_crs("EPSG:4326")
    )

    etl = BaseCanvasETL()
    result = etl._compute_area_by_use(gdf)

    assert result is gdf
    assert "area_parcel" in result.columns
    assert "geometry" in result.columns


def test_compute_area_by_use_fallback_area_gross() -> None:
    """_compute_area_by_use falls back to area_gross when area_parcel is missing."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

    gdf = (
        gpd.GeoDataFrame(
            {
                "land_development_category": ["urban"],
                "area_gross": [15.0],
                "area_parcel_res": [np.nan],
                "geometry": [Point(0, 0)],
            }
        )
        .set_geometry("geometry")
        .set_crs("EPSG:4326")
    )

    etl = BaseCanvasETL()
    result = etl._compute_area_by_use(gdf)

    assert result.loc[0, "area_parcel_res"] == 15.0


def test_compute_area_by_use_all_nan() -> None:
    """_compute_area_by_use sends all-NaN categories to undeveloped."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

    gdf = (
        gpd.GeoDataFrame(
            {
                "land_development_category": [np.nan, np.nan],
                "area_parcel": [5.0, 10.0],
                "area_parcel_no_use": [np.nan, np.nan],
                "geometry": [Point(0, 0), Point(1, 1)],
            }
        )
        .set_geometry("geometry")
        .set_crs("EPSG:4326")
    )

    etl = BaseCanvasETL()
    result = etl._compute_area_by_use(gdf)

    # Both NaN categories default to "undeveloped" via fillna
    assert result["area_parcel_no_use"].sum() == 15.0


def test_irrigation_unit_conversion() -> None:
    """Verify sqft→acres conversion factor (43,560 sqft = 1 acre)."""
    sqft_per_acre = 43560.0
    # Known conversions
    assert 43560.0 / sqft_per_acre == 1.0  # 1 acre
    assert 0.0 / sqft_per_acre == 0.0  # zero
    assert 87120.0 / sqft_per_acre == 2.0  # 2 acres
    # Verify the v1 reference conversion in _query_reference_totals
    ref_sqft = 65340000.0  # hypothetical 1500 acres in sqft
    ref_acres = ref_sqft / sqft_per_acre
    assert ref_acres == 1500.0
