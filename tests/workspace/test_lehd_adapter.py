"""Tests for LEHD employment polygon geometry fetching and adapter."""
from __future__ import annotations

from unittest.mock import patch

import geopandas as gpd
from shapely.geometry import Point

from brewgis.workspace.services.base_canvas_adapters import (
    LEHDEmploymentSource,
    NullEmploymentSource,
)


class TestNullEmploymentSource:
    """Null source should report unavailable and return empty."""

    def test_not_available(self) -> None:
        source = NullEmploymentSource()
        assert not source.available

    def test_fetch_returns_empty(self) -> None:
        source = NullEmploymentSource()
        result = source.fetch_block_data()
        assert isinstance(result, gpd.GeoDataFrame)
        assert result.empty


class TestLEHDEmploymentSource:
    """Tests for the LEHDEmploymentSource adapter."""

    def test_available_with_fips(self) -> None:
        """Source should be available when state/county FIPS are set."""
        source = LEHDEmploymentSource(state_fips="06", county_fips="019")
        assert source.available

    def test_not_available_without_fips(self) -> None:
        """Source should not be available without FIPS codes."""
        source = LEHDEmploymentSource(state_fips="", county_fips="")
        assert not source.available

    @patch.object(LEHDEmploymentSource, "fetch_block_data", autospec=True)
    def test_fetch_delegates_to_lehd_fetcher(self, mock_fetch) -> None:
        """fetch_block_data should return data."""
        mock_fetch.return_value = gpd.GeoDataFrame(
            {"geoid": ["060190001001000"], "emp": [500]},
            geometry=[Point(-119.5, 36.5)],
        )
        source = LEHDEmploymentSource(state_fips="06", county_fips="019")
        result = source.fetch_block_data()
        assert not result.empty
        assert result.iloc[0]["emp"] == 500

    def test_caches_data(self) -> None:
        """Repeated calls should return cached data without re-fetching."""
        source = LEHDEmploymentSource(state_fips="06", county_fips="019")
        with patch(
            "brewgis.workspace.services.lehd_fetcher.fetch_lehd_block_polygons",
        ) as mock_fetch:
            mock_fetch.return_value = gpd.GeoDataFrame(
                {"geoid": ["060190001001000"], "emp": [500]},
                geometry=[Point(-119.5, 36.5)],
            )
            result1 = source.fetch_block_data()
            assert not result1.empty
            assert mock_fetch.call_count == 1

        result2 = source.fetch_block_data()
        assert not result2.empty
        assert result2.iloc[0]["emp"] == 500


class TestLEHDEmploymentColumns:
    """Tests that LEHD employment columns cover ETL expectations."""

    def test_wac_variables_map_to_canvas_names(self) -> None:
        """WAC_VARIABLES should map CA codes to recognizable column names."""
        from brewgis.workspace.services.lehd_fetcher import WAC_VARIABLES

        wac_cols = set(WAC_VARIABLES.values())
        assert "emp" in wac_cols
        assert "emp_ag" in wac_cols
        assert "emp_retail" in wac_cols
        assert "emp_mfg" in wac_cols

    def test_agg_mappings_produce_aggregates(self) -> None:
        """AGGREGATE_MAPPINGS should contain all aggregate employment columns."""
        from brewgis.workspace.services.lehd_fetcher import AGGREGATE_MAPPINGS

        expected = {"emp_ret", "emp_off", "emp_pub", "emp_ind", "emp_ag", "emp_military"}
        assert expected.issubset(AGGREGATE_MAPPINGS.keys())
