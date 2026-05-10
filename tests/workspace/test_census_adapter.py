"""Tests for Census ACS polygon geometry fetching and adapter."""
from __future__ import annotations

from unittest.mock import patch

import geopandas as gpd
from shapely.geometry import Point

from brewgis.workspace.services.base_canvas_adapters import (
    CensusDemographicSource,
    NullDemographicSource,
)


class TestNullDemographicSource:
    """Null source should report unavailable and return empty."""

    def test_not_available(self) -> None:
        source = NullDemographicSource()
        assert not source.available

    def test_fetch_returns_empty(self) -> None:
        source = NullDemographicSource()
        result = source.fetch_block_group_data()
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.empty


class TestCensusDemographicSource:
    """Tests for the CensusDemographicSource adapter."""

    def test_available_with_fips(self) -> None:
        """Source should be available when state/county FIPS are set."""
        source = CensusDemographicSource(state_fips="06", county_fips="019")
        assert source.available

    def test_not_available_without_fips(self) -> None:
        """Source should not be available without FIPS codes."""
        source = CensusDemographicSource(state_fips="", county_fips="")
        assert not source.available

    @patch.object(CensusDemographicSource, "fetch_block_group_data", autospec=True)
    def test_fetch_delegates_to_census_fetcher(self, mock_fetch) -> None:
        """fetch_block_group_data should return data."""
        mock_fetch.return_value = gpd.GeoDataFrame(
            {"geoid": ["060190001001"], "pop": [5000]},
            geometry=[Point(-119.5, 36.5)],
        )
        source = CensusDemographicSource(state_fips="06", county_fips="019")
        result = source.fetch_block_group_data()
        assert not result.empty
        assert result.iloc[0]["pop"] == 5000

    def test_caches_data(self) -> None:
        """Repeated calls should return cached data without re-fetching."""
        source = CensusDemographicSource(state_fips="06", county_fips="019")
        with patch(
            "brewgis.workspace.services.census_fetcher.fetch_acs_block_group_polygons",
        ) as mock_fetch:
            mock_fetch.return_value = gpd.GeoDataFrame(
                {"geoid": ["060190001001"], "pop": [5000]},
                geometry=[Point(-119.5, 36.5)],
            )
            result1 = source.fetch_block_group_data()
            assert not result1.empty
            assert mock_fetch.call_count == 1

        result2 = source.fetch_block_group_data()
        assert not result2.empty
        assert result2.iloc[0]["pop"] == 5000


class TestACSColumnMapping:
    """Tests for ACS column mapping logic."""

    def test_column_mapping_du_subtypes(self) -> None:
        """du_mf_2_9 should be split into du_mf2to4 and du_mf5p."""
        from brewgis.workspace.services.census_fetcher import _apply_acs_column_mapping

        gdf = gpd.GeoDataFrame(
            {
                "geoid": ["001"],
                "du_mf_2_9": [100.0],
                "du_mf_10p": [50.0],
                "du_detsf": [200.0],
                "pop": [5000],
            },
            geometry=[Point(-119.5, 36.5)],
        )
        result = _apply_acs_column_mapping(gdf)
        assert "du_mf2to4" in result.columns
        assert "du_mf5p" in result.columns
        assert "du_detsf_sl" in result.columns
        assert "du_detsf_ll" in result.columns
        assert result.iloc[0]["du_mf2to4"] == 40.0
        assert result.iloc[0]["du_mf5p"] == 110.0
        assert result.iloc[0]["du_detsf_sl"] == 80.0
        assert result.iloc[0]["du_detsf_ll"] == 120.0

    def test_column_mapping_missing_du(self) -> None:
        """Missing DU columns should default to 0."""
        from brewgis.workspace.services.census_fetcher import _apply_acs_column_mapping

        gdf = gpd.GeoDataFrame(
            {"geoid": ["001"], "pop": [5000]},
            geometry=[Point(-119.5, 36.5)],
        )
        result = _apply_acs_column_mapping(gdf)
        assert result.iloc[0]["du_mf2to4"] == 0.0
        assert result.iloc[0]["du_mf5p"] == 0.0
        assert result.iloc[0]["du_detsf_sl"] == 0.0
        assert result.iloc[0]["du_detsf_ll"] == 0.0

    def test_cost_burden_pct_computed(self) -> None:
        """cost_burden_pct should combine owner (B25091) and renter (B25070) burden."""
        from brewgis.workspace.services.census_fetcher import _compute_derived_columns

        row = {
            "B01001_001E": 5000,
            "B25003_001E": 2000,
            "B25003_002E": 1200,
            "B25003_003E": 800,
            "B25024_001E": 2200,
            "B25024_002E": 1500,
            "B25024_003E": 200,
            "B25024_004E": 100,
            "B25024_005E": 50,
            "B25024_006E": 100,
            "B25024_007E": 100,
            "B25024_008E": 100,
            "B25024_009E": 50,
            "B19013_001E": 60000,
            "B25070_001E": 800,
            "B25070_007E": 50,
            "B25070_008E": 50,
            "B25070_009E": 50,
            "B25070_010E": 50,
            "B25091_001E": 1200,
            "B25091_005E": 50,
            "B25091_006E": 50,
            "B25091_007E": 50,
            "B25091_011E": 50,
            "B25091_012E": 50,
            "B25091_013E": 50,
            "B03002_001E": 5000,
            "B03002_002E": 3000,
            "B15003_001E": 4000,
            "B15003_022E": 500,
            "B15003_023E": 300,
            "B15003_024E": 100,
            "B15003_025E": 100,
        }
        result = _compute_derived_columns(row)
        assert result["cost_burden_pct"] == 25.0
