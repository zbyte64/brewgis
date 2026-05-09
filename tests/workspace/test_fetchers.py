"""Tests for data fetcher services (Census, LEHD, POI)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from brewgis.workspace.services.census_fetcher import ACS_TABLE_GROUPS
from brewgis.workspace.services.census_fetcher import _all_vars
from brewgis.workspace.services.census_fetcher import _build_census_url
from brewgis.workspace.services.census_fetcher import _compute_derived_columns
from brewgis.workspace.services.census_fetcher import fetch_acs_block_groups
from brewgis.workspace.services.census_fetcher import fetch_acs_data_summary
from brewgis.workspace.services.lehd_fetcher import WAC_VARIABLES
from brewgis.workspace.services.lehd_fetcher import _all_wac_vars
from brewgis.workspace.services.lehd_fetcher import _build_wac_url
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_data
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_data_summary
from brewgis.workspace.services.poi_fetcher import POI_CATEGORIES
from brewgis.workspace.services.poi_fetcher import _build_overpass_query
from brewgis.workspace.services.poi_fetcher import _categorize_element

# ── Census Fetcher Tests ─────────────────────────────────────────────


class TestCensusFetcher:
    """Unit tests for the Census ACS fetcher service."""

    def test_all_vars_returns_all_codes(self) -> None:
        """_all_vars should return every variable code across all table groups."""
        vars_ = _all_vars()
        expected_count = sum(len(g["vars"]) for g in ACS_TABLE_GROUPS.values())
        assert len(vars_) == expected_count
        assert "B01001_001E" in vars_
        assert "B25024_001E" in vars_

    def test_build_census_url_block_group(self) -> None:
        """URL should be correctly formatted for block group level."""
        url = _build_census_url("06", "067", "block group")
        assert "api.census.gov/data/2022/acs/acs5" in url
        assert "state:06" in url
        assert "county:067" in url
        assert "block%20group" in url

    def test_build_census_url_tract(self) -> None:
        """URL should be correctly formatted for tract level."""
        url = _build_census_url("06", "067", "tract")
        assert "tract" in url

    def test_compute_derived_columns(self) -> None:
        """Derived canvas columns should be computed correctly."""
        row = {
            "B01001_001E": 5000,
            "B25003_001E": 2000,
            "B25003_002E": 1200,
            "B25003_003E": 800,
            "B25024_001E": 2200,
            "B25024_002E": 1500,  # detached SF
            "B25024_003E": 200,  # attached SF
            "B25024_004E": 100,  # 2 units
            "B25024_005E": 50,  # 3-4
            "B25024_006E": 100,  # 5-9
            "B25024_007E": 100,  # 10-19
            "B25024_008E": 100,  # 20-49
            "B25024_009E": 50,  # 50+
        }
        result = _compute_derived_columns(row)
        assert result["pop"] == 5000
        assert result["hh"] == 2000
        assert result["du"] == 2200
        assert result["du_detsf"] == 1500
        assert result["du_attsf"] == 200
        assert result["du_mf_2_9"] == 250  # 100 + 50 + 100
        assert result["du_mf_10p"] == 250  # 100 + 100 + 50

    def test_compute_derived_columns_missing_values(self) -> None:
        """Missing values should default to 0."""
        result = _compute_derived_columns({})
        assert result["pop"] == 0
        assert result["hh"] == 0
        assert result["du"] == 0

    @patch("brewgis.workspace.services.census_fetcher.requests.get")
    def test_fetch_acs_census_api_error(self, mock_get) -> None:
        """API HTTP errors should raise RuntimeError."""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"

        with pytest.raises(RuntimeError, match="Census API returned HTTP 500"):
            fetch_acs_block_groups("06", "067")

    @patch("brewgis.workspace.services.census_fetcher.requests.get")
    def test_fetch_acs_data_summary_success(self, mock_get) -> None:
        """Data summary should return expected structure on success."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            # header + data rows
            ["B01001_001E", "state", "county", "tract", "block group"],
            ["100", "06", "067", "100100", "1"],
            ["200", "06", "067", "100200", "2"],
        ]

        summary = fetch_acs_data_summary("06", "067")
        assert summary["row_count"] == 2
        assert "B01001" in summary["table_groups"]
        assert "pop" in summary["columns"]

    @patch("brewgis.workspace.services.census_fetcher.requests.get")
    def test_fetch_acs_data_summary_api_error(self, mock_get) -> None:
        """Data summary should return error dict on API failure."""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Error"

        summary = fetch_acs_data_summary("06", "067")
        assert "error" in summary

    @patch("brewgis.workspace.services.census_fetcher.requests.get")
    def test_fetch_acs_empty_response(self, mock_get) -> None:
        """Empty API response should raise RuntimeError."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [["header", "cols"]]

        with pytest.raises(RuntimeError, match="Census API returned no data rows"):
            fetch_acs_block_groups("06", "067")


# ── LEHD Fetcher Tests ────────────────────────────────────────────────


class TestLEHDFetcher:
    """Unit tests for the LEHD employment fetcher service."""

    def test_all_wac_vars(self) -> None:
        """_all_wac_vars should return all WAC variable codes."""
        vars_ = _all_wac_vars()
        assert "C000" in vars_
        assert len(vars_) == len(WAC_VARIABLES)

    def test_build_wac_url(self) -> None:
        """URL should be correctly formatted."""
        url = _build_wac_url("06", "067")
        assert "api.census.gov/data/2021/lehd/wac" in url
        assert "state:06" in url
        assert "county:067" in url
        assert "for=block" in url

    @patch("brewgis.workspace.services.lehd_fetcher.requests.get")
    def test_fetch_lehd_api_error(self, mock_get) -> None:
        """API HTTP errors should raise RuntimeError."""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Error"

        with pytest.raises(RuntimeError, match="LEHD API returned HTTP 500"):
            fetch_lehd_block_data("06", "067")

    @patch("brewgis.workspace.services.lehd_fetcher.requests.get")
    def test_fetch_lehd_empty_response(self, mock_get) -> None:
        """Empty API response should raise RuntimeError."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [["C000", "state"]]

        with pytest.raises(RuntimeError, match="LEHD API returned no data rows"):
            fetch_lehd_block_data("06", "067")

    @patch("brewgis.workspace.services.lehd_fetcher.requests.get")
    def test_fetch_lehd_data_summary_success(self, mock_get) -> None:
        """Data summary should return expected structure."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            ["C000", "state", "county", "tract", "block"],
            ["500", "06", "067", "100100", "1000"],
        ]

        summary = fetch_lehd_data_summary("06", "067")
        assert summary["row_count"] == 1
        assert "emp" in summary["variables"]
        assert "emp_ret" in summary["aggregate_columns"]

    @patch("brewgis.workspace.services.lehd_fetcher.requests.get")
    def test_fetch_lehd_data_summary_api_error(self, mock_get) -> None:
        """Data summary should return error dict on API failure."""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Error"

        summary = fetch_lehd_data_summary("06", "067")
        assert "error" in summary


# ── POI Fetcher Tests ─────────────────────────────────────────────────


class TestPOIFetcher:
    """Unit tests for the POI fetcher service."""

    def test_poi_categories_populated(self) -> None:
        """POI_CATEGORIES should have all expected categories."""
        assert "restaurants" in POI_CATEGORIES
        assert "schools" in POI_CATEGORIES
        assert "hospitals" in POI_CATEGORIES
        assert "parks" in POI_CATEGORIES
        assert "transit" in POI_CATEGORIES
        assert "shopping" in POI_CATEGORIES

    def test_build_overpass_query_basic(self) -> None:
        """Overpass query should include bbox and tag filters."""
        query = _build_overpass_query(
            -121.5, 38.4, -121.2, 38.7, categories=["restaurants"]
        )
        assert "38.4,-121.5,38.7,-121.2" in query
        assert "amenity" in query
        assert "restaurant" in query
        assert "[out:json]" in query

    def test_build_overpass_query_all_categories(self) -> None:
        """Query with None categories should include all tags."""
        query = _build_overpass_query(-121.5, 38.4, -121.2, 38.7, categories=None)
        # Should include many different tag filters
        assert query.count("amenity") > 3
        assert query.count("leisure") > 1

    def test_build_overpass_query_empty_categories(self) -> None:
        """Empty categories list should fall back to restaurants."""
        query = _build_overpass_query(-121.5, 38.4, -121.2, 38.7, categories=[])
        assert "restaurant" in query

    def test_categorize_element_restaurant(self) -> None:
        """A restaurant node should be categorized correctly."""
        cat, sub = _categorize_element({"amenity": "restaurant"})
        assert cat == "restaurants"
        assert sub == "amenity=restaurant"

    def test_categorize_element_school(self) -> None:
        """A school node should be categorized correctly."""
        cat, sub = _categorize_element({"amenity": "school"})
        assert cat == "schools"
        assert sub == "amenity=school"

    def test_categorize_element_unknown(self) -> None:
        """An unrecognized tag should return 'unknown'."""
        cat, sub = _categorize_element({"foo": "bar"})
        assert cat == "unknown"
        assert sub == "unknown"

    def test_categorize_element_hospital(self) -> None:
        """A hospital should be categorized under hospitals."""
        cat, sub = _categorize_element({"amenity": "hospital"})
        assert cat == "hospitals"

    def test_categorize_element_park(self) -> None:
        """A park should be categorized under parks."""
        cat, sub = _categorize_element({"leisure": "park"})
        assert cat == "parks"

    def test_categorize_element_transit(self) -> None:
        """A bus station should be categorized under transit."""
        cat, sub = _categorize_element({"amenity": "bus_station"})
        assert cat == "transit"

    def test_categorize_element_shopping(self) -> None:
        """A supermarket should be categorized under shopping."""
        cat, sub = _categorize_element({"shop": "supermarket"})
        assert cat == "shopping"
