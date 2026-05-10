"""Tests for NLCD and OSM adapters (land classification, irrigation, intersection density)."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np

from brewgis.workspace.services.base_canvas_adapters import (
    NullIntersectionDensitySource,
)
from brewgis.workspace.services.base_canvas_adapters import NullIrrigationSource
from brewgis.workspace.services.base_canvas_adapters import NullLandUseSource
from brewgis.workspace.services.base_canvas_adapters import classify_by_assessor_code
from brewgis.workspace.services.nlcd_fetcher import _verify_cached_file


class TestNullLandUseSource:
    """Null sources should report unavailable."""

    def test_not_available(self) -> None:
        assert not NullLandUseSource().available
        assert not NullIrrigationSource().available
        assert not NullIntersectionDensitySource().available


class TestNLCDClassification:
    """NLCD land cover classification rules."""

    def test_urban_from_developed(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([22, 22, 22, 41, 81], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "urban"

    def test_industrial_from_high_intensity(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([24, 24, 24, 22], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "industrial"

    def test_agricultural_from_crops(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([81, 81, 82, 21], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "agricultural"

    def test_natural_from_forest(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        pixels = np.array([41, 42, 43, 51], dtype=np.uint8)
        assert _nlcd_majority_class(pixels) == "natural"

    def test_empty_pixels_returns_unknown(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _nlcd_majority_class

        assert _nlcd_majority_class(None) == "unknown"
        assert _nlcd_majority_class(np.array([])) == "unknown"

    def test_impervious_fraction_computed(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import (
            _estimate_nlcd_impervious_fraction,
        )

        pixels = np.array([21, 22, 23, 24], dtype=np.uint8)
        expected = (0.10 + 0.30 + 0.60 + 0.85) / 4
        result = _estimate_nlcd_impervious_fraction(pixels)
        assert abs(result - expected) < 0.01

    def test_impervious_empty_returns_zero(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import (
            _estimate_nlcd_impervious_fraction,
        )

        assert _estimate_nlcd_impervious_fraction(None) == 0.0
        assert _estimate_nlcd_impervious_fraction(np.array([])) == 0.0


class TestAssessorClassification:
    """Assessor use code classification rules."""

    def test_residential_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="R") == "urban"
        assert classify_land_development(assessor_use_code="R1") == "urban"
        assert classify_land_development(assessor_use_code="RES") == "urban"
        assert classify_land_development(assessor_use_code="SFR") == "urban"
        assert classify_land_development(assessor_use_code="MFR") == "urban"
        assert classify_land_development(assessor_use_code="CONDO") == "urban"

    def test_commercial_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="COM") == "industrial"
        assert classify_land_development(assessor_use_code="RET") == "industrial"

    def test_industrial_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="IND") == "industrial"
        assert classify_land_development(assessor_use_code="MFG") == "industrial"
        assert classify_land_development(assessor_use_code="WARE") == "industrial"

    def test_agricultural_codes(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development(assessor_use_code="AG") == "agricultural"
        assert classify_land_development(assessor_use_code="FARM") == "agricultural"

    def test_default_to_urban(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        assert classify_land_development() == "urban"
        assert classify_land_development(assessor_use_code="UNKNOWN") == "urban"

    def test_nlcd_majority_used_when_no_code(self) -> None:
        from brewgis.workspace.services.nlcd_fetcher import classify_land_development

        result = classify_land_development(nlcd_majority="agricultural")
        assert result == "agricultural"

class TestAssessorCodeClassification:
    """Tests for ``classify_by_assessor_code`` (numerical CA codes)."""

    def test_residential_prefix(self) -> None:
        assert classify_by_assessor_code("10") == "urban"
        assert classify_by_assessor_code("11") == "urban"
        assert classify_by_assessor_code("18") == "urban"

    def test_agricultural_prefix(self) -> None:
        assert classify_by_assessor_code("40") == "agricultural"
        assert classify_by_assessor_code("41") == "agricultural"
        assert classify_by_assessor_code("46") == "agricultural"

    def test_undeveloped_prefix(self) -> None:
        assert classify_by_assessor_code("50") == "undeveloped"
        assert classify_by_assessor_code("60") == "undeveloped"
        assert classify_by_assessor_code("70") == "undeveloped"

    def test_industrial_prefix(self) -> None:
        assert classify_by_assessor_code("30") == "urban"

    def test_none_input(self) -> None:
        assert classify_by_assessor_code(None) is None

    def test_empty_string(self) -> None:
        assert classify_by_assessor_code("") is None
        assert classify_by_assessor_code("   ") is None

    def test_unknown_code(self) -> None:
        assert classify_by_assessor_code("99") is None
        assert classify_by_assessor_code("00") is None

    def test_full_four_digit_code(self) -> None:
        # "4012" → prefix "40" → "agricultural"
        assert classify_by_assessor_code("4012") == "agricultural"
        assert classify_by_assessor_code("1011") == "urban"

    def test_integer_input(self) -> None:
        assert classify_by_assessor_code(40) == "agricultural"
        assert classify_by_assessor_code(10) == "urban"
        assert classify_by_assessor_code(50) == "undeveloped"
        assert classify_by_assessor_code(99) is None

    def test_single_digit_code(self) -> None:
        assert classify_by_assessor_code("4") is None  # "4" not in map
        assert classify_by_assessor_code("1") is None


class TestNullLandUseSourceAssessorCodes:
    """Tests for NullLandUseSource with assessor use codes."""

    def test_classifies_by_assessor_code(self) -> None:
        import shapely.geometry as geom

        parcels = gpd.GeoDataFrame(
            {
                "assessor_use_code": ["40", "10", "50", "99", None],
                "geometry": [geom.Point(0, 0).buffer(0.01) for _ in range(5)],
            },
            crs="EPSG:4326",
        )
        parcels["land_development_category"] = None
        source = NullLandUseSource()
        result = source.classify_parcels(parcels)
        assert list(result["land_development_category"]) == [
            "agricultural",
            "urban",
            "undeveloped",
            None,
            None,
        ]

    def test_does_not_overwrite_existing_values(self) -> None:
        import shapely.geometry as geom

        parcels = gpd.GeoDataFrame(
            {
                "assessor_use_code": ["40", "10"],
                "land_development_category": ["existing_value", None],
                "geometry": [geom.Point(0, 0).buffer(0.01) for _ in range(2)],
            },
            crs="EPSG:4326",
        )
        source = NullLandUseSource()
        result = source.classify_parcels(parcels)
        assert result["land_development_category"].iloc[0] == "existing_value"
        assert result["land_development_category"].iloc[1] == "urban"

    def test_no_assessor_code_column(self) -> None:
        import shapely.geometry as geom

        parcels = gpd.GeoDataFrame(
            {
                "land_development_category": [None, None],
                "geometry": [geom.Point(0, 0).buffer(0.01) for _ in range(2)],
            },
            crs="EPSG:4326",
        )
        source = NullLandUseSource()
        result = source.classify_parcels(parcels)
        # No assessor code column → nothing changes
        assert result["land_development_category"].isna().all()


class TestVerifyCachedFile:
    """Tests for _verify_cached_file integrity check."""

    def test_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.img"
        assert _verify_cached_file(missing) is False

    def test_empty_file_removed(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.img"
        empty.write_bytes(b"")
        assert _verify_cached_file(empty) is False
        assert not empty.exists()

    def test_size_mismatch_removed(self, tmp_path: Path) -> None:
        f = tmp_path / "test.img"
        f.write_bytes(b"some data")
        assert _verify_cached_file(f, expected_size=999) is False
        assert not f.exists()

    def test_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "valid.img"
        f.write_bytes(b"valid content")
        assert _verify_cached_file(f) is True
        assert f.exists()


class TestNlcdWcsDownload:
    """Tests for _download_nlcd_subset WCS path."""

    def test_download_creates_cache_file(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from brewgis.workspace.services.nlcd_fetcher import _download_nlcd_subset

        fake_tif = b"fake-geotiff-content-for-testing"

        with patch("brewgis.workspace.services.nlcd_fetcher.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = fake_tif
            mock_get.return_value.raise_for_status.return_value = None

            result = _download_nlcd_subset(
                west=-121.5,
                south=38.0,
                east=-121.0,
                north=38.5,
                year=2021,
                cache_dir=tmp_path,
            )

        assert result is not None
        assert Path(result).exists()
        assert Path(result).read_bytes() == fake_tif

    def test_cache_hit_returns_existing(self, tmp_path: Path) -> None:
        from brewgis.workspace.services.nlcd_fetcher import _download_nlcd_subset

        cached = tmp_path / "nlcd_2021_-121_5_38_0_-121_0_38_5.tif"
        cached.write_bytes(b"cached-data")

        result = _download_nlcd_subset(
            west=-121.5,
            south=38.0,
            east=-121.0,
            north=38.5,
            year=2021,
            cache_dir=tmp_path,
        )

        assert result == str(cached)
        assert cached.read_bytes() == b"cached-data"

    def test_refresh_cache_removes_old(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from brewgis.workspace.services.nlcd_fetcher import _download_nlcd_subset

        stale = tmp_path / "nlcd_2021_-121_5_38_0_-121_0_38_5.tif"
        stale.write_bytes(b"stale-data")

        fake_tif = b"fresh-data"

        with patch("brewgis.workspace.services.nlcd_fetcher.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = fake_tif
            mock_get.return_value.raise_for_status.return_value = None

            result = _download_nlcd_subset(
                west=-121.5,
                south=38.0,
                east=-121.0,
                north=38.5,
                year=2021,
                cache_dir=tmp_path,
                refresh_cache=True,
            )

        assert result is not None
        assert Path(result).read_bytes() == b"fresh-data"

    def test_wcs_url_constructed_correctly(self, tmp_path: Path) -> None:
        """Verify the WCS request is built with correct parameters."""
        from unittest.mock import patch

        from brewgis.workspace.services.nlcd_fetcher import _MRLC_WCS_URL
        from brewgis.workspace.services.nlcd_fetcher import _download_nlcd_subset

        with patch("brewgis.workspace.services.nlcd_fetcher.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = b"data"
            mock_get.return_value.raise_for_status.return_value = None

            _download_nlcd_subset(
                west=-120.0,
                south=37.0,
                east=-119.5,
                north=37.5,
                year=2021,
                cache_dir=tmp_path,
            )

        mock_get.assert_called_once_with(
            _MRLC_WCS_URL,
            params={
                "service": "WCS",
                "version": "2.0.1",
                "request": "GetCoverage",
                "CoverageId": "nlcd_2021_land_cover_l48",
                "subset": ["X(-120.0,-119.5)", "Y(37.0,37.5)"],
                "format": "image/geotiff",
            },
            timeout=300,
        )


class TestNlcdFetcherBbox:
    """Tests NLCDFetcher computes bbox from parcels."""

    def test_classify_parcels_computes_bbox(self) -> None:
        """Verify classify_parcels computes a buffered bbox from parcel bounds."""
        from unittest.mock import patch

        import geopandas as gpd
        from shapely import wkt

        from brewgis.workspace.services.base_canvas_adapters import NLCDFetcher

        parcels = gpd.GeoDataFrame(
            {"parcel_id": [1, 2]},
            geometry=[
                wkt.loads("POLYGON ((-121.5 38.0, -121.0 38.0, -121.0 38.5, -121.5 38.5, -121.5 38.0))"),
                wkt.loads("POLYGON ((-121.0 38.5, -120.5 38.5, -120.5 39.0, -121.0 39.0, -121.0 38.5))"),
            ],
            crs="EPSG:4326",
        )

        fetcher = NLCDFetcher(bbox=(-999, -999, 999, 999))  # bogus default, should be overridden

        with patch(
            "brewgis.workspace.services.nlcd_fetcher.compute_nlcd_zonal_stats",
        ) as mock_compute:
            mock_compute.return_value = parcels
            fetcher.classify_parcels(parcels)

        mock_compute.assert_called_once()
        call_bbox = mock_compute.call_args[0][1]  # second positional arg

        # Expected: total_bounds = [-121.5, 38.0, -120.5, 39.0]
        # With 5 % buffer: x_pad = 1.0 * 0.05 = 0.05, y_pad = 1.0 * 0.05 = 0.05
        # bbox = (-121.55, 37.95, -120.45, 39.05)
        expected_west, expected_south, expected_east, expected_north = (-121.55, 37.95, -120.45, 39.05)
        actual_west, actual_south, actual_east, actual_north = call_bbox

        assert abs(actual_west - expected_west) < 0.001
        assert abs(actual_south - expected_south) < 0.001
        assert abs(actual_east - expected_east) < 0.001
        assert abs(actual_north - expected_north) < 0.001

class TestOSMIntersectionDensityJurisdiction:
    """Tests for jurisdiction-level intersection density computation."""

    def test_compute_density_groups_by_jurisdiction(self) -> None:
        """Verify density is computed at jurisdiction level, not per-parcel."""
        from unittest.mock import patch

        import geopandas as gpd
        from shapely import wkt

        from brewgis.workspace.services.base_canvas_adapters import (
            OSMIntersectionDensitySource,
        )

        parcels = gpd.GeoDataFrame(
            {
                "parcel_id": [1, 2, 3],
                "jurisdiction": ["UrbanCity", "UrbanCity", "SuburbTown"],
                "area_gross": [10.0, 10.0, 20.0],
            },
            geometry=[
                wkt.loads(
                    "POLYGON ((-121.5 38.0, -121.4 38.0, -121.4 38.1, -121.5 38.1, -121.5 38.0))"
                ),
                wkt.loads(
                    "POLYGON ((-121.5 38.1, -121.4 38.1, -121.4 38.2, -121.5 38.2, -121.5 38.1))"
                ),
                wkt.loads(
                    "POLYGON ((-121.3 38.0, -121.2 38.0, -121.2 38.1, -121.3 38.1, -121.3 38.0))"
                ),
            ],
            crs="EPSG:4326",
        )
        source = OSMIntersectionDensitySource(bbox=(-122, 37, -121, 39))

        with patch.object(
            OSMIntersectionDensitySource, "available", return_value=True,
        ), patch.object(
            source, "_compute_jurisdiction_density",
        ) as mock_jd:
            def side_effect(jp: gpd.GeoDataFrame) -> float | None:
                juris = jp["jurisdiction"].iloc[0]
                return {"UrbanCity": 40.0, "SuburbTown": 10.0}.get(juris)

            mock_jd.side_effect = side_effect
            result = source.compute_density(parcels)

        assert "intersection_density" in result.columns
        assert result.loc[0, "intersection_density"] == 40.0
        assert result.loc[1, "intersection_density"] == 40.0
        assert result.loc[2, "intersection_density"] == 10.0
        assert mock_jd.call_count == 2

    def test_fallback_to_default_on_jurisdiction_failure(self) -> None:
        """Verify fallback to DEFAULT_DENSITY when jurisdiction computation returns None."""
        from unittest.mock import patch

        import geopandas as gpd
        from shapely import wkt

        from brewgis.workspace.services.base_canvas_adapters import (
            OSMIntersectionDensitySource,
        )

        parcels = gpd.GeoDataFrame(
            {
                "parcel_id": [1],
                "jurisdiction": ["Nowhere"],
                "area_gross": [10.0],
            },
            geometry=[
                wkt.loads(
                    "POLYGON ((-121.5 38.0, -121.4 38.0, -121.4 38.1, -121.5 38.1, -121.5 38.0))"
                ),
            ],
            crs="EPSG:4326",
        )
        source = OSMIntersectionDensitySource(bbox=(-122, 37, -121, 39))

        with patch.object(
            OSMIntersectionDensitySource, "available", return_value=True,
        ), patch.object(
            source, "_compute_jurisdiction_density", return_value=None,
        ):
            result = source.compute_density(parcels)

        assert "intersection_density" in result.columns
        assert result.loc[0, "intersection_density"] == OSMIntersectionDensitySource.DEFAULT_DENSITY

    def test_fallback_to_per_parcel_when_no_jurisdiction(self) -> None:
        """Verify fallback to per-parcel computation when no jurisdiction column."""
        from unittest.mock import patch

        import geopandas as gpd
        from shapely import wkt

        from brewgis.workspace.services.base_canvas_adapters import (
            OSMIntersectionDensitySource,
        )

        parcels = gpd.GeoDataFrame(
            {
                "parcel_id": [1],
                "area_gross": [10.0],
            },
            geometry=[
                wkt.loads(
                    "POLYGON ((-121.5 38.0, -121.4 38.0, -121.4 38.1, -121.5 38.1, -121.5 38.0))"
                ),
            ],
            crs="EPSG:4326",
        )
        source = OSMIntersectionDensitySource(bbox=(-122, 37, -121, 39))

        with patch.object(
            OSMIntersectionDensitySource, "available", return_value=True,
        ), patch.object(
            source, "_compute_per_parcel",
        ) as mock_per_parcel:
            mock_per_parcel.return_value = parcels
            source.compute_density(parcels)

        mock_per_parcel.assert_called_once()

    def test_unavailable_source_returns_parcels(self) -> None:
        """Verify unavailable source returns parcels without intersection_density."""
        import geopandas as gpd
        from shapely import wkt

        from unittest.mock import patch

        from brewgis.workspace.services.base_canvas_adapters import (
            OSMIntersectionDensitySource,
        )

        parcels = gpd.GeoDataFrame(
            {
                "parcel_id": [1],
                "jurisdiction": ["City"],
                "area_gross": [10.0],
            },
            geometry=[
                wkt.loads(
                    "POLYGON ((-121.5 38.0, -121.4 38.0, -121.4 38.1, -121.5 38.1, -121.5 38.0))"
                ),
            ],
            crs="EPSG:4326",
        )
        source = OSMIntersectionDensitySource(bbox=(-122, 37, -121, 39))

        with patch.object(
            OSMIntersectionDensitySource, "available", False,
        ):
            result = source.compute_density(parcels)

        # Without osmnx, the method returns early; intersection_density not filled
        assert "intersection_density" not in result.columns
