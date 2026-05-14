"""Tests for LEHD → LODES employment polygon geometry fetching and adapter."""

from __future__ import annotations

import io
import csv
from unittest.mock import MagicMock
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import requests
import pytest
from shapely.geometry import Point

from brewgis.workspace.services.base_canvas_adapters import LEHDEmploymentSource
from brewgis.workspace.services.base_canvas_adapters import NullEmploymentSource
from brewgis.workspace.services.lehd_fetcher import _NAICS_SPLIT_RULES
from brewgis.workspace.services.lehd_fetcher import AGGREGATE_MAPPINGS
from brewgis.workspace.services.lehd_fetcher import LODES_WAC_VARIABLES
from brewgis.workspace.services.lehd_fetcher import _apply_naics_splits
from brewgis.workspace.services.lehd_fetcher import _build_cbp_proportions
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_block_data
from brewgis.workspace.services.lehd_fetcher import fetch_county_employment_scaling
from brewgis.workspace.services.lehd_fetcher import _cbp_url
from brewgis.workspace.services.lehd_fetcher import _fetch_cbp_county_emp

_FAKE_CBP_JSON: list[list[str]] = [
    ["EMP", "NAICS2017", "state", "county"],
    ["----", "----", "06", "019"],
    ["100", "------", "06", "019"],
    ["10", "11----", "06", "019"],
    ["5", "21----", "06", "019"],
    ["20", "23----", "06", "019"],
    ["50", "31----", "06", "019"],
    ["8", "22----", "06", "019"],
    ["12", "42----", "06", "019"],
    ["30", "44----", "06", "019"],
    ["5", "45----", "06", "019"],
    ["10", "48----", "06", "019"],
    ["3", "49----", "06", "019"],
    ["15", "721---", "06", "019"],
    ["25", "722---", "06", "019"],
]


def _fake_lodes_csv() -> str:
    """Return a minimal LODES WAC CSV string for testing."""
    lines = [
        "w_geocode,C000,CNS01,CNS02,CNS03,CNS04,CNS05,CNS06,CNS07,CNS08,CNS09,"
        "CNS10,CNS11,CNS12,CNS13,CNS14,CNS15,CNS16,CNS17",
        "060190001001000,500,50,100,80,10,15,5,20,8,12,30,40,5,15,10,25,0,3",
        "060190001001001,200,20,40,30,5,8,2,10,4,6,15,20,2,8,5,12,0,1",
    ]
    return "\n".join(lines)


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


class TestLODESWACVariables:
    """Tests that LODES WAC variables are defined correctly."""

    def test_lodes_wac_variables_defined(self) -> None:
        """LODES_WAC_VARIABLES should contain C000 and CNS codes."""

        assert "C000" in LODES_WAC_VARIABLES
        assert "CNS01" in LODES_WAC_VARIABLES
        assert "CNS17" in LODES_WAC_VARIABLES
        assert LODES_WAC_VARIABLES["C000"] == "emp"

    def test_agg_mappings_produce_aggregates(self) -> None:
        """AGGREGATE_MAPPINGS should contain all aggregate employment columns."""

        expected = {
            "emp_ret",
            "emp_off",
            "emp_pub",
            "emp_ind",
            "emp_ag",
            "emp_military",
        }
        assert expected.issubset(AGGREGATE_MAPPINGS.keys())

    def test_agg_mappings_sub_sector_columns(self) -> None:
        """AGGREGATE_MAPPINGS detail lists should all have entries."""

        for agg_key, detail_cols in AGGREGATE_MAPPINGS.items():
            assert len(detail_cols) > 0, f"{agg_key} has empty detail list"


class TestNAICSSplitRules:
    """Tests for the NAICS split rules configuration."""

    def test_split_rules_defined(self) -> None:
        """All CNS codes should have split rules."""

        assert "CNS01" in _NAICS_SPLIT_RULES
        assert "CNS05" in _NAICS_SPLIT_RULES
        assert "CNS11" in _NAICS_SPLIT_RULES
        assert "CNS17" in _NAICS_SPLIT_RULES

    def test_split_rules_cover_all_sub_sectors(self) -> None:
        """Split rules should produce all expected employment sub-sector columns."""

        produced = set()
        for rules in _NAICS_SPLIT_RULES.values():
            for col, _ in rules:
                produced.add(col)

        expected = {
            "emp_retail_services",
            "emp_restaurant",
            "emp_accommodation",
            "emp_arts_entertainment",
            "emp_other_services",
            "emp_office_services",
            "emp_medical_services",
            "emp_public_admin",
            "emp_education",
            "emp_manufacturing",
            "emp_wholesale",
            "emp_transport_warehousing",
            "emp_utilities",
            "emp_construction",
            "emp_agriculture",
            "emp_extraction",
            "emp_military",
        }
        assert expected.issubset(produced), f"Missing: {expected - produced}"


class TestCBPProportions:
    """Tests for the CBP proportion computation logic."""

    def test_cbp_proportions_parse(self) -> None:
        """_build_cbp_proportions should parse CBP JSON and return proportions."""

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = _FAKE_CBP_JSON
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            props = _build_cbp_proportions("06", "019", 2021)

        # Should have proportions for goods-producing prefixes
        assert "11" in props
        assert "21" in props
        assert "23" in props
        # Proportions within goods-producing should sum to ~1.0
        goods_sum = props.get("11", 0) + props.get("21", 0) + props.get("23", 0)
        assert abs(goods_sum - 1.0) < 0.01

        # Should have 721/722 accommodation-food split
        assert "721" in props
        assert "722" in props
        acc_food_sum = props.get("721", 0) + props.get("722", 0)
        assert abs(acc_food_sum - 1.0) < 0.01

    def test_cbp_proportions_returns_empty_on_http_error(self) -> None:
        """_build_cbp_proportions should return empty dict on HTTP error."""

        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("HTTP error")
            props = _build_cbp_proportions("06", "019")
            assert props == {}

    def test_cbp_proportions_returns_empty_on_bad_json(self) -> None:
        """_build_cbp_proportions should return empty dict on bad JSON."""

        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.side_effect = ValueError("bad json")
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            props = _build_cbp_proportions("06", "019")
            assert props == {}


class TestApplyNAICSSplits:
    """Tests for the NAICS split computation logic."""

    def test_direct_mapping(self) -> None:
        """A rule with fraction=1.0 should map the full CNS value."""

        # CNS11 (Health Care) → emp_medical_services (1.0)
        result = _apply_naics_splits({"CNS11": 100}, {})
        assert result.get("emp_medical_services", 0) == 100.0

    def test_fractional_split(self) -> None:
        """CNS02 (Manufacturing) → 1.0 emp_manufacturing."""

        # CNS02 (Manufacturing) → 1.0 emp_manufacturing (was 0.7/0.3 wholesale)
        result = _apply_naics_splits({"CNS02": 100}, {})
        assert result.get("emp_manufacturing", 0) == 100.0
        assert result.get("emp_wholesale", 0) == 0  # wholesale no longer from CNS02

    def test_remainder_split(self) -> None:
        """Last rule with None should absorb the remainder."""

        # CNS03 with CBP: transport=0.2, utilities=0.1, wholesale=0.15 → remainder=0.55 for retail
        cbp = {"48": 0.15, "49": 0.05, "22": 0.10, "42": 0.15}
        result = _apply_naics_splits({"CNS03": 100}, cbp)
        assert result.get("emp_transport_warehousing", 0) == 20.0
        assert result.get("emp_utilities", 0) == 10.0
        assert result.get("emp_wholesale", 0) == 15.0  # wholesale from CBP (42)
        assert result.get("emp_retail_services", 0) == 55.0

    def test_zero_cns_produces_zeros(self) -> None:
        """Zero CNS values should produce zero for all related sub-sectors."""

        result = _apply_naics_splits({}, {})
        for key in (
            "emp_agriculture",
            "emp_extraction",
            "emp_construction",
            "emp_military",
        ):
            assert result.get(key, 0) == 0.0

    def test_cbp_proportion_used(self) -> None:
        """A NAICS regex rule should pull the CBP proportion."""

        # CNS01: CBP says agriculture (11) = 0.1, extraction (21) = 0.2
        cbp = {"11": 0.1, "21": 0.2, "23": 0.7}
        result = _apply_naics_splits({"CNS01": 100}, cbp)
        assert abs(result.get("emp_agriculture", 0) - 10.0) < 0.01
        assert abs(result.get("emp_extraction", 0) - 20.0) < 0.01
        assert abs(result.get("emp_construction", 0) - 70.0) < 0.01

    def test_same_target_accumulates(self) -> None:
        """Multiple CNS codes mapping to the same target should accumulate."""

        # CNS04 + CNS05 + CNS06 all → emp_office_services
        result = _apply_naics_splits({"CNS04": 10, "CNS05": 15, "CNS06": 5}, {})
        assert result.get("emp_office_services", 0) == 30.0


class TestFetchLODESBlockData:
    """Tests for the LODES block data fetching with sub-sector columns."""

    @patch("brewgis.workspace.services.lehd_fetcher._build_cbp_proportions")
    @patch("brewgis.workspace.services.lehd_fetcher.get_engine")
    def test_fetch_lodes_block_data_produces_all_columns(
        self,
        mock_engine: MagicMock,
        mock_cbp: MagicMock,
    ) -> None:
        """fetch_lehd_block_data should produce all sub-sector and aggregate columns."""

        mock_cbp.return_value = {
            "11": 0.1,
            "21": 0.05,
            "23": 0.85,
            "48": 0.1,
            "49": 0.05,
            "22": 0.08,
            "42": 0.15,
            "44": 0.4,
            "45": 0.07,
            "721": 0.35,
            "722": 0.65,
        }

        reader = csv.DictReader(io.StringIO(_fake_lodes_csv()))
        keys = reader.fieldnames + ["year"]
        rows = [tuple(row[col] for col in reader.fieldnames) + (2021,) for row in reader]
        mock_result = mock_engine.return_value.connect.return_value.__enter__.return_value.execute.return_value
        mock_result.fetchall.return_value = rows
        mock_result.keys.return_value = keys
        result = fetch_lehd_block_data("06", "019")

        assert not result.empty
        assert result.iloc[0]["geoid"] == "060190001001000"
        assert result.iloc[0]["emp"] == 500

        # Check sub-sector columns exist
        sub_sector_cols = [
            "emp_retail_services",
            "emp_restaurant",
            "emp_accommodation",
            "emp_arts_entertainment",
            "emp_other_services",
            "emp_office_services",
            "emp_medical_services",
            "emp_public_admin",
            "emp_education",
            "emp_manufacturing",
            "emp_wholesale",
            "emp_transport_warehousing",
            "emp_utilities",
            "emp_construction",
            "emp_agriculture",
            "emp_extraction",
            "emp_military",
        ]
        for col in sub_sector_cols:
            assert col in result.columns, f"Missing column: {col}"

        # Check aggregate columns exist
        for col in (
            "emp",
            "emp_ret",
            "emp_off",
            "emp_pub",
            "emp_ind",
            "emp_ag",
            "emp_military",
        ):
            assert col in result.columns, f"Missing aggregate column: {col}"

    @patch("brewgis.workspace.services.lehd_fetcher._build_cbp_proportions")
    @patch("brewgis.workspace.services.lehd_fetcher.get_engine")
    def test_non_zero_sub_sectors(
        self,
        mock_engine: MagicMock,
        mock_cbp: MagicMock,
    ) -> None:
        """Sub-sector columns should have non-zero values when CNS data is non-zero."""

        mock_cbp.return_value = {
            "11": 0.2,
            "21": 0.1,
            "23": 0.7,
            "48": 0.15,
            "49": 0.05,
            "22": 0.1,
            "42": 0.07,
            "721": 0.35,
            "722": 0.65,
        }

        reader = csv.DictReader(io.StringIO(_fake_lodes_csv()))
        keys = reader.fieldnames + ["year"]
        rows = [tuple(row[col] for col in reader.fieldnames) + (2021,) for row in reader]
        mock_result = mock_engine.return_value.connect.return_value.__enter__.return_value.execute.return_value
        mock_result.fetchall.return_value = rows
        mock_result.keys.return_value = keys

        result = fetch_lehd_block_data("06", "019")

        row = result.iloc[0]

        # All CNS columns should produce non-zero sub-sector values
        non_zero_expected = [
            "emp_agriculture",
            "emp_extraction",
            "emp_construction",  # CNS01
            "emp_manufacturing",  # CNS02
            "emp_retail_services",
            "emp_transport_warehousing",
            "emp_utilities",
            "emp_wholesale",  # CNS03
            "emp_office_services",  # CNS04-09
            "emp_education",  # CNS10
            "emp_medical_services",  # CNS11
            "emp_arts_entertainment",  # CNS12
            "emp_accommodation",
            "emp_restaurant",  # CNS13
            "emp_other_services",  # CNS14
            "emp_public_admin",  # CNS15
            "emp_military",  # CNS17
        ]
        for col in non_zero_expected:
            assert row[col] > 0, f"Column {col} should be > 0 but was {row[col]}"

        # Aggregate columns should be non-zero
        for agg_col in (
            "emp",
            "emp_ret",
            "emp_off",
            "emp_pub",
            "emp_ind",
            "emp_ag",
            "emp_military",
        ):
            assert row[agg_col] > 0, (
                f"Aggregate column {agg_col} should be > 0 but was {row[agg_col]}"
            )
    @patch("brewgis.workspace.services.lehd_fetcher._build_cbp_proportions")
    @patch("brewgis.workspace.services.lehd_fetcher.get_engine")
    def test_total_emp_consistency(
        self,
        mock_engine: MagicMock,
        mock_cbp: MagicMock,
    ) -> None:
        """emp (C000 total jobs) should be self-consistent."""

        mock_cbp.return_value = {
            "11": 0.2,
            "21": 0.1,
            "23": 0.7,
            "48": 0.15,
            "49": 0.05,
            "22": 0.1,
            "42": 0.07,
            "721": 0.35,
            "722": 0.65,
        }

        reader = csv.DictReader(io.StringIO(_fake_lodes_csv()))
        keys = reader.fieldnames + ["year"]
        rows = [tuple(row[col] for col in reader.fieldnames) + (2021,) for row in reader]
        mock_result = mock_engine.return_value.connect.return_value.__enter__.return_value.execute.return_value
        mock_result.fetchall.return_value = rows
        mock_result.keys.return_value = keys

        result = fetch_lehd_block_data("06", "019")
        row = result.iloc[0]

        # emp (C000) is the ground truth
        assert row["emp"] == 500

class TestCBPCountyScaling:
    """Tests for the CBP county-level employment scaling computation."""

    def test_cbp_url_construction(self) -> None:
        """_cbp_url should build the correct API URL."""
        url = _cbp_url("06", "019", "44")
        assert "NAICS2017=44----" in url
        assert "county:019" in url
        assert "state:06" in url
        assert "EMP" in url

    def test_fetch_cbp_county_emp_parses_response(self) -> None:
        """_fetch_cbp_county_emp should parse EMP from API response."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = [
                ["EMP", "NAICS2017", "state", "county"],
                ["500", "44----", "06", "019"],
            ]
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            result = _fetch_cbp_county_emp("06", "019", {"retail": "44"})
        assert result["retail"] == 500.0

    def test_fetch_cbp_county_emp_suppressed_data(self) -> None:
        """Suppressed values (D, S, N) should return 0.0."""
        for suppressed in ("D", "S", "N", ""):
            with patch("requests.get") as mock_get:
                mock_response = MagicMock()
                mock_response.json.return_value = [
                    ["EMP", "NAICS2017", "state", "county"],
                    [suppressed, "44----", "06", "019"],
                ]
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response
                result = _fetch_cbp_county_emp("06", "019", {"retail": "44"})
            assert result["retail"] == 0.0, f"Expected 0.0 for {suppressed!r}"

    def test_fetch_cbp_county_emp_http_error(self) -> None:
        """HTTP errors should propagate, not be swallowed."""
        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("fail")
            with pytest.raises(requests.RequestException):
                _fetch_cbp_county_emp("06", "019", {"retail": "44"})

    def test_cbp_scaling_all_sectors_above_one(self) -> None:
        """Scaling factor should be >1 when CBP exceeds LEHD."""
        lehd_gdf = gpd.GeoDataFrame(
            {
                "geoid": ["060190001001000"],
                "emp": [100],
                "emp_ret": [10],
                "emp_off": [20],
                "emp_pub": [15],
                "emp_ind": [30],
            },
            geometry=[Point(-119.5, 36.5)],
        )
        with patch(
            "brewgis.workspace.services.lehd_fetcher.fetch_lehd_block_data",
            return_value=lehd_gdf,
        ):
            with patch(
                "brewgis.workspace.services.lehd_fetcher._fetch_cbp_county_emp",
            ) as mock_cbp:
                # CBP totals per code aggregated per sector:
                # emp_ret: 44=500, 45=0     → 500 total
                # emp_off: 51=0, 52=0, 53=0, 54=0, 55=0, 56=0 → 0
                # emp_pub: 61=0, 62=0, 92=0 → 0
                # emp_ind: 11=100, 21=0, 22=0, 23=0, 31=0, 32=0,
                #          33=0, 42=0, 48=0, 49=0 → 100 total
                mock_cbp.return_value = {
                    "emp_ret_44": 500.0,
                    "emp_ret_45": 0.0,
                    "emp_off_51": 0.0,
                    "emp_off_52": 0.0,
                    "emp_off_53": 0.0,
                    "emp_off_54": 0.0,
                    "emp_off_55": 0.0,
                    "emp_off_56": 0.0,
                    "emp_pub_61": 0.0,
                    "emp_pub_62": 0.0,
                    "emp_pub_92": 0.0,
                    "emp_ind_11": 100.0,
                    "emp_ind_21": 0.0,
                    "emp_ind_22": 0.0,
                    "emp_ind_23": 0.0,
                    "emp_ind_31": 0.0,
                    "emp_ind_32": 0.0,
                    "emp_ind_33": 0.0,
                    "emp_ind_42": 0.0,
                    "emp_ind_48": 0.0,
                    "emp_ind_49": 0.0,
                }
                scale = fetch_county_employment_scaling("06", "019")

        # emp_ret: CBP=500, LEHD=10 → scale=50.0
        assert scale["emp_ret"] == 50.0
        # emp_off: CBP=0 → no change
        assert scale["emp_off"] == 1.0
        # emp_pub: CBP=0 → no change
        assert scale["emp_pub"] == 1.0
        # emp_ind: CBP=100, LEHD=30 → scale=3.33...
        assert scale["emp_ind"] == pytest.approx(100.0 / 30.0)

    def test_cbp_scaling_never_scales_down(self) -> None:
        """Scaling factor should never be below 1.0."""
        lehd_gdf = gpd.GeoDataFrame(
            {
                "geoid": ["060190001001000"],
                "emp": [100],
                "emp_ret": [50],
                "emp_off": [50],
                "emp_pub": [50],
                "emp_ind": [50],
            },
            geometry=[Point(-119.5, 36.5)],
        )
        with patch(
            "brewgis.workspace.services.lehd_fetcher.fetch_lehd_block_data",
            return_value=lehd_gdf,
        ):
            with patch(
                "brewgis.workspace.services.lehd_fetcher._fetch_cbp_county_emp",
            ) as mock_cbp:
                # CBP data is LOWER than LEHD for all sectors
                mock_cbp.return_value = {
                    "emp_ret_44": 10.0,
                    "emp_ret_45": 0.0,
                    "emp_off_51": 10.0,
                    "emp_off_52": 0.0,
                    "emp_off_53": 0.0,
                    "emp_off_54": 0.0,
                    "emp_off_55": 0.0,
                    "emp_off_56": 0.0,
                    "emp_pub_61": 10.0,
                    "emp_pub_62": 0.0,
                    "emp_pub_92": 0.0,
                    "emp_ind_11": 10.0,
                    "emp_ind_21": 0.0,
                    "emp_ind_22": 0.0,
                    "emp_ind_23": 0.0,
                    "emp_ind_31": 0.0,
                    "emp_ind_32": 0.0,
                    "emp_ind_33": 0.0,
                    "emp_ind_42": 0.0,
                    "emp_ind_48": 0.0,
                    "emp_ind_49": 0.0,
                }
                scale = fetch_county_employment_scaling("06", "019")

        # All should be 1.0 (never scale down)
        assert scale["emp_ret"] == 1.0
        assert scale["emp_off"] == 1.0
        assert scale["emp_pub"] == 1.0
        assert scale["emp_ind"] == 1.0

    def test_cbp_scaling_lehd_unavailable(self) -> None:
        """When LEHD data fetch fails, the RuntimeError propagates."""
        with patch(
            "brewgis.workspace.services.lehd_fetcher.fetch_lehd_block_data",
            side_effect=RuntimeError("No data"),
        ):
            with pytest.raises(RuntimeError):
                fetch_county_employment_scaling("06", "019")

    def test_cbp_scaling_zero_lehd_sector(self) -> None:
        """When LEHD sector total is 0, should return 1.0 (avoid division by zero)."""
        lehd_gdf = gpd.GeoDataFrame(
            {
                "geoid": ["060190001001000"],
                "emp": [100],
                "emp_ret": [0],
                "emp_off": [0],
                "emp_pub": [0],
                "emp_ind": [0],
            },
            geometry=[Point(-119.5, 36.5)],
        )
        with patch(
            "brewgis.workspace.services.lehd_fetcher.fetch_lehd_block_data",
            return_value=lehd_gdf,
        ):
            with patch(
                "brewgis.workspace.services.lehd_fetcher._fetch_cbp_county_emp",
            ) as mock_cbp:
                mock_cbp.return_value = {
                    "emp_ret_44": 100.0,
                    "emp_ret_45": 0.0,
                    "emp_off_51": 100.0,
                    "emp_off_52": 0.0,
                    "emp_off_53": 0.0,
                    "emp_off_54": 0.0,
                    "emp_off_55": 0.0,
                    "emp_off_56": 0.0,
                    "emp_pub_61": 100.0,
                    "emp_pub_62": 0.0,
                    "emp_pub_92": 0.0,
                    "emp_ind_11": 100.0,
                    "emp_ind_21": 0.0,
                    "emp_ind_22": 0.0,
                    "emp_ind_23": 0.0,
                    "emp_ind_31": 0.0,
                    "emp_ind_32": 0.0,
                    "emp_ind_33": 0.0,
                    "emp_ind_42": 0.0,
                    "emp_ind_48": 0.0,
                    "emp_ind_49": 0.0,
                }
                scale = fetch_county_employment_scaling("06", "019")

        # Division by zero avoided → all default to 1.0
        assert scale == {"emp_ret": 1.0, "emp_off": 1.0, "emp_pub": 1.0, "emp_ind": 1.0}
