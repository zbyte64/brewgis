"""Tests for the Sacramento County Assessor parcel fetcher service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from brewgis.workspace.services.assessor_fetcher import _PAGE_SIZE
from brewgis.workspace.services.assessor_fetcher import _PARCEL_FIELDS
from brewgis.workspace.services.assessor_fetcher import _SALES_FIELDS
from brewgis.workspace.services.assessor_fetcher import PARCELS_MAP_SERVER
from brewgis.workspace.services.assessor_fetcher import SALES_MAP_SERVER
from brewgis.workspace.services.assessor_fetcher import _arcgis_features_to_gdf
from brewgis.workspace.services.assessor_fetcher import _arcgis_query_paginated
from brewgis.workspace.services.assessor_fetcher import fetch_parcels_arcgis
from brewgis.workspace.services.assessor_fetcher import fetch_sales_arcgis
from brewgis.workspace.services.assessor_fetcher import load_to_postgis


def _make_mock_response(features: list[dict]) -> MagicMock:
    """Create a mock requests.Response-like object."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"features": features}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_parcel_props(i: int) -> dict:
    """Create a mock parcel feature properties dict."""
    return {
        "properties": {"PARCEL_NUMBER": f"P{i:05d}"},
        "geometry": {"type": "Point", "coordinates": [-121.5, 38.5]},
    }


class TestArcGisPagination:
    """Tests for ArcGIS pagination logic."""

    def test_pagination_offset_calculation(self) -> None:
        """Offset should increment by PAGE_SIZE after each page."""
        offsets = [page * _PAGE_SIZE for page in range(3)]
        assert offsets == [0, 2000, 4000]

    def test_pagination_stops_on_empty_page(self) -> None:
        """_arcgis_query_paginated should stop when fewer than PAGE_SIZE features returned."""
        mock_resp = _make_mock_response([_make_parcel_props(i) for i in range(50)])

        with patch("requests.get", return_value=mock_resp):
            result = _arcgis_query_paginated(
                PARCELS_MAP_SERVER, ["PARCEL_NUMBER"], max_pages=5
            )
        assert len(result) == 50
        assert result[0]["PARCEL_NUMBER"] == "P00000"

    def test_pagination_respects_max_pages(self) -> None:
        """_arcgis_query_paginated should stop after max_pages even if more data exists."""
        mock_resp = _make_mock_response(
            [_make_parcel_props(i) for i in range(_PAGE_SIZE)]
        )

        with patch("requests.get", return_value=mock_resp):
            result = _arcgis_query_paginated(
                PARCELS_MAP_SERVER, ["PARCEL_NUMBER"], max_pages=2
            )
        assert len(result) == _PAGE_SIZE * 2

    def test_pagination_multiple_pages_merges_results(self) -> None:
        """Results from multiple pages should be merged into a single list."""
        first_page = _make_mock_response(
            [_make_parcel_props(i) for i in range(_PAGE_SIZE)]
        )
        second_page = _make_mock_response(
            [_make_parcel_props(i) for i in range(_PAGE_SIZE, _PAGE_SIZE * 2)]
        )
        third_page = _make_mock_response([])

        with patch("requests.get", side_effect=[first_page, second_page, third_page]):
            result = _arcgis_query_paginated(
                PARCELS_MAP_SERVER, ["PARCEL_NUMBER"], max_pages=3
            )
        assert len(result) == _PAGE_SIZE * 2
        assert result[0]["PARCEL_NUMBER"] == "P00000"
        assert result[-1]["PARCEL_NUMBER"] == f"P{_PAGE_SIZE * 2 - 1:05d}"

    def test_pagination_api_failure_propagates(self) -> None:
        """ArcGIS API failures should propagate as exceptions."""
        with (
            patch("requests.get", side_effect=ConnectionError("API unavailable")),
            pytest.raises(ConnectionError),
        ):
            _arcgis_query_paginated(PARCELS_MAP_SERVER, ["PARCEL_NUMBER"])


class TestArcGisGeoJSONParsing:
    """Tests for ArcGIS GeoJSON-to-GeoDataFrame conversion."""

    def test_arcgis_features_to_gdf_basic(self) -> None:
        """GeoJSON features with point geometry should convert to GeoDataFrame."""
        features = [
            {
                "PARCEL_NUMBER": "001-0020-003",
                "geometry": '{"type":"Point","coordinates":[-121.5,38.5]}',
            },
            {
                "PARCEL_NUMBER": "001-0020-004",
                "geometry": '{"type":"Point","coordinates":[-121.51,38.51]}',
            },
        ]
        gdf = _arcgis_features_to_gdf(features)
        assert len(gdf) == 2
        assert list(gdf.columns) == ["PARCEL_NUMBER", "geometry"]
        assert gdf.crs.to_string() == "EPSG:4326"

    def test_arcgis_features_to_gdf_missing_geometry(self) -> None:
        """Features without geometry should get None geometry without error."""
        features = [
            {"PARCEL_NUMBER": "001-0020-003"},
            {"PARCEL_NUMBER": "001-0020-004"},
        ]
        gdf = _arcgis_features_to_gdf(features)
        assert len(gdf) == 2
        assert gdf.geometry.isnull().all()

    def test_arcgis_features_to_gdf_empty_list(self) -> None:
        """Empty feature list should produce empty GeoDataFrame."""
        gdf = _arcgis_features_to_gdf([])
        assert gdf.empty

    def test_arcgis_features_to_gdf_polygon_geometry(self) -> None:
        """Polygon GeoJSON should parse to polygon geometry."""
        polygon_geo = (
            '{"type":"Polygon","coordinates":[['
            "[-121.5,38.5],[-121.49,38.5],[-121.49,38.51],"
            "[-121.5,38.51],[-121.5,38.5]]]}"
        )
        features = [{"PARCEL_NUMBER": "001-0020-003", "geometry": polygon_geo}]
        gdf = _arcgis_features_to_gdf(features)
        assert len(gdf) == 1
        assert gdf.geometry.iloc[0].geom_type == "Polygon"


class TestCacheBehavior:
    """Tests for caching behavior in fetch functions."""

    def test_fetch_parcels_uses_cache(self, tmp_path: Path) -> None:
        """When cache exists, fetch_parcels_arcgis should read from cache not API."""
        cache_dir = tmp_path / "planning"  # type: ignore[operator]
        cache_dir.mkdir(parents=True)

        dummy_gdf = gpd.GeoDataFrame(
            {"apn": ["001"]},
            geometry=[Point(-121.5, 38.5)],
            crs="EPSG:4326",
        )
        dummy_gdf.to_parquet(cache_dir / "sacog_assessor_parcels.parquet")

        with (
            patch(
                "brewgis.workspace.services.assessor_fetcher.CACHE_DIR",
                cache_dir,
            ),
            patch("requests.get") as mock_get,
        ):
            result = fetch_parcels_arcgis(ignore_cache=False)
            mock_get.assert_not_called()
            assert len(result) == 1
            assert result["apn"].iloc[0] == "001"

    def test_fetch_parcels_ignores_cache_when_forced(self, tmp_path: Path) -> None:
        """When ignore_cache=True, fetch_parcels_arcgis should re-download."""
        cache_dir = tmp_path / "planning"  # type: ignore[operator]
        cache_dir.mkdir(parents=True)

        dummy_gdf = gpd.GeoDataFrame(
            {"apn": ["001"]},
            geometry=[Point(-121.5, 38.5)],
            crs="EPSG:4326",
        )
        dummy_gdf.to_parquet(cache_dir / "sacog_assessor_parcels.parquet")

        mock_resp = _make_mock_response(
            [
                {
                    "properties": {"PARCEL_NUMBER": "002-0030-004"},
                    "geometry": {"type": "Point", "coordinates": [-121.5, 38.5]},
                }
            ]
        )

        with (
            patch(
                "brewgis.workspace.services.assessor_fetcher.CACHE_DIR",
                cache_dir,
            ),
            patch("requests.get", return_value=mock_resp),
        ):
            result = fetch_parcels_arcgis(ignore_cache=True)
            assert len(result) == 1
            assert result["apn"].iloc[0] == "002-0030-004"

    def test_fetch_sales_uses_cache(self, tmp_path: Path) -> None:
        """When cache exists, fetch_sales_arcgis should read from cache not API."""
        cache_dir = tmp_path / "planning"  # type: ignore[operator]
        cache_dir.mkdir(parents=True)

        dummy_gdf = gpd.GeoDataFrame(
            {"apn": ["001"], "living_area": [1500.0]},
            geometry=[Point(-121.5, 38.5)],
            crs="EPSG:4326",
        )
        dummy_gdf.to_parquet(cache_dir / "sacog_assessor_sales.parquet")

        with (
            patch(
                "brewgis.workspace.services.assessor_fetcher.CACHE_DIR",
                cache_dir,
            ),
            patch("requests.get") as mock_get,
        ):
            result = fetch_sales_arcgis(ignore_cache=False)
            mock_get.assert_not_called()
            assert len(result) == 1
            assert result["living_area"].iloc[0] == 1500.0


class TestLoadToPostGIS:
    """Tests for the load_to_postgis function."""

    def test_load_to_postgis_with_parcels(self) -> None:
        """load_to_postgis should write parcel data and return row count."""
        parcels = gpd.GeoDataFrame(
            {"apn": ["001", "002"]},
            geometry=[Point(-121.5, 38.5), Point(-121.51, 38.51)],
            crs="EPSG:4326",
        )

        with patch.object(gpd.GeoDataFrame, "to_postgis"):
            result = load_to_postgis(parcels=parcels)

        assert "sacog_assessor_parcels_raw" in result
        assert result["sacog_assessor_parcels_raw"] == 2

    def test_load_to_postgis_empty_parcels(self) -> None:
        """load_to_postgis should skip writing when parcels is None."""
        result = load_to_postgis(parcels=None)
        assert result == {}

    def test_load_to_postgis_empty_dataframe(self) -> None:
        """load_to_postgis should skip writing when parcels GeoDataFrame is empty."""
        empty_gdf = gpd.GeoDataFrame()
        result = load_to_postgis(parcels=empty_gdf)
        assert result == {}


class TestAssessorFetcherParcelFields:
    """Tests for parcel field constants."""

    def test_parcel_fields_contain_expected_columns(self) -> None:
        """_PARCEL_FIELDS should include key columns from MapServer/8."""
        assert "PARCEL_NUMBER" in _PARCEL_FIELDS
        assert "LANDUSE" in _PARCEL_FIELDS
        assert "LOTSIZE" in _PARCEL_FIELDS
        assert "JURISDICTION" in _PARCEL_FIELDS
        assert "ZONE_" in _PARCEL_FIELDS

    def test_sales_fields_contain_expected_columns(self) -> None:
        """_SALES_FIELDS should include key columns from MapServer/1."""
        assert "PARCEL_NUMBER" in _SALES_FIELDS
        assert "TOTAL_LIVING_AREA" in _SALES_FIELDS
        assert "BUILDING_SF" in _SALES_FIELDS
        assert "EFFECTIVE_YEAR_BUILT" in _SALES_FIELDS
        assert "Property_Type" in _SALES_FIELDS
        assert "INDICATED_SALES_PRICE" in _SALES_FIELDS

    def test_parcels_map_server_url_format(self) -> None:
        """PARCELS_MAP_SERVER should be a valid ArcGIS REST query URL."""
        assert PARCELS_MAP_SERVER.endswith("/query")
        assert "saccounty" in PARCELS_MAP_SERVER

    def test_sales_map_server_url_format(self) -> None:
        """SALES_MAP_SERVER should be a valid ArcGIS REST query URL."""
        assert SALES_MAP_SERVER.endswith("/query")
        assert "saccounty" in SALES_MAP_SERVER


@pytest.mark.integration
class TestAssessorFetcherIntegration:
    """Integration tests that hit the real ArcGIS API (1 page only)."""

    def test_fetch_one_page_parcels(self) -> None:
        """Fetch 1 page of parcel data and verify schema + geometry."""
        result = _arcgis_query_paginated(
            PARCELS_MAP_SERVER,
            _PARCEL_FIELDS,
            max_pages=1,
        )
        assert len(result) > 0
        assert len(result) <= _PAGE_SIZE
        first = result[0]
        assert "PARCEL_NUMBER" in first
        assert "geometry" in first
        assert first["PARCEL_NUMBER"] is not None

    def test_fetch_one_page_sales(self) -> None:
        """Fetch 1 page of sales data and verify schema."""
        result = _arcgis_query_paginated(
            SALES_MAP_SERVER,
            _SALES_FIELDS,
            max_pages=1,
        )
        assert len(result) > 0
        assert len(result) <= _PAGE_SIZE
        first = result[0]
        assert "PARCEL_NUMBER" in first
        assert "geometry" in first
        has_building_col = "TOTAL_LIVING_AREA" in first or "BUILDING_SF" in first
        assert has_building_col

    def test_fetch_and_convert_one_page_parcels(self) -> None:
        """Fetch 1 page of parcels and convert to GeoDataFrame."""
        features = _arcgis_query_paginated(
            PARCELS_MAP_SERVER,
            _PARCEL_FIELDS,
            max_pages=1,
        )
        gdf = _arcgis_features_to_gdf(features)
        assert len(gdf) > 0
        assert gdf.crs is not None
        assert gdf.crs.to_string() == "EPSG:4326"
        assert all(gdf.geometry.notnull())
