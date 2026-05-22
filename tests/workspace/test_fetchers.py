"""Tests for data fetcher services (Census, LEHD, POI)."""

from __future__ import annotations

from unittest.mock import patch

from brewgis.workspace.services.census_fetcher import ACS_TABLE_GROUPS
from brewgis.workspace.services.census_fetcher import _all_vars
from brewgis.workspace.services.census_fetcher import fetch_acs_data_summary
from brewgis.workspace.services.lehd_fetcher import LODES_WAC_VARIABLES
from brewgis.workspace.services.lehd_fetcher import _all_lodes_wac_vars
from brewgis.workspace.services.lehd_fetcher import _build_lodes_wac_url
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

    def test_fetch_acs_data_summary_from_staging(self) -> None:
        """Data summary should return expected structure from staging."""
        with patch(
            "brewgis.workspace.services.census_fetcher.get_engine"
        ) as mock_get_engine:
            mock_conn = (
                mock_get_engine.return_value.connect.return_value.__enter__.return_value
            )
            mock_conn.execute.return_value.scalar.return_value = 42
            summary = fetch_acs_data_summary("06", "067")
        assert summary["row_count"] == 42
        assert "B01001" in summary["table_groups"]
        assert "pop" in summary["columns"]


# ── LEHD Fetcher Tests ────────────────────────────────────────────────


class TestLEHDFetcher:
    """Unit tests for the LEHD employment fetcher service."""

    def test_all_lodes_wac_vars(self) -> None:
        """_all_lodes_wac_vars should return all LODES WAC variable codes."""
        vars_ = _all_lodes_wac_vars()
        assert "C000" in vars_
        assert len(vars_) == len(LODES_WAC_VARIABLES)

    def test_build_lodes_wac_url(self) -> None:
        """URL should be correctly formatted."""
        url = _build_lodes_wac_url("06", "067")
        assert "lehd.ces.census.gov/data/lodes/LODES8" in url
        assert "ca" in url
        assert "S000_JT00_2021.csv.gz" in url
        assert "wac" in url

    def test_fetch_lehd_data_summary_from_staging(self) -> None:
        """Data summary should return expected structure from staging."""
        with patch(
            "brewgis.workspace.services.lehd_fetcher.get_engine"
        ) as mock_get_engine:
            mock_conn = (
                mock_get_engine.return_value.connect.return_value.__enter__.return_value
            )
            mock_conn.execute.return_value.scalar.return_value = 100
            summary = fetch_lehd_data_summary("06", "067")
        assert summary["row_count"] == 100
        assert "C000" in summary["variables"]
        assert "emp_ret" in summary["aggregate_columns"]

    def test_compute_all_cbp_totals_parses_api_response(self) -> None:
        """_compute_all_cbp_totals should correctly map NAICS codes to sub-sector columns."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        from brewgis.workspace.services.lehd_fetcher import _compute_all_cbp_totals

        # Simulate CBP API response with various NAICS codes and employment counts
        mock_response = MagicMock()
        mock_response.json.return_value = [
            ["EMP", "NAICS2017", "state", "county"],
            ["50000", "31----", "06", "067"],
            ["30000", "32----", "06", "067"],
            ["20000", "33----", "06", "067"],
            ["8000", "42----", "06", "067"],
            ["12000", "44----", "06", "067"],
            ["5000", "45----", "06", "067"],
            ["15000", "48----", "06", "067"],
            ["3000", "49----", "06", "067"],
            ["4000", "22----", "06", "067"],
            ["6000", "23----", "06", "067"],
            ["7000", "721---", "06", "067"],
            ["25000", "722---", "06", "067"],
            ["55000", "51----", "06", "067"],
            ["35000", "52----", "06", "067"],
            ["90000", "62----", "06", "067"],
            ["40000", "61----", "06", "067"],
            ["30000", "92----", "06", "067"],
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["8000", "71----", "06", "067"],
            ["12000", "81----", "06", "067"],
        ]
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        with _patch(
            "brewgis.workspace.services.lehd_fetcher.requests.get",
            return_value=mock_response,
        ):
            with _patch(
                "brewgis.workspace.services.lehd_fetcher._census_api_key",
                return_value="test_key",
            ):
                result = _compute_all_cbp_totals("06", "067", year=2011)

        assert "emp_manufacturing" in result
        assert result["emp_manufacturing"] == 100000  # 31+32+33
        assert result["emp_retail_services"] == 17000  # 44+45
        assert result["emp_wholesale"] == 8000
        assert result["emp_transport_warehousing"] == 18000  # 48+49
        assert result["emp_utilities"] == 4000
        assert result["emp_construction"] == 6000
        assert result["emp_accommodation"] == 7000
        assert result["emp_restaurant"] == 25000
        assert result["emp_office_services"] == 90000  # 51+52
        assert result["emp_medical_services"] == 90000
        assert result["emp_education"] == 40000
        assert result["emp_public_admin"] == 30000
        assert result["emp_agriculture"] == 10000
        assert result["emp_extraction"] == 2000
        assert result["emp_arts_entertainment"] == 8000
        assert result["emp_other_services"] == 12000
        assert "emp_military" not in result
        assert abs(sum(result.values()) - 467000) < 0.01

    def test_compute_all_cbp_totals_returns_empty_on_api_failure(self) -> None:
        """_compute_all_cbp_totals should return empty dict on API failure."""
        from unittest.mock import patch as _patch

        import requests

        from brewgis.workspace.services.lehd_fetcher import _compute_all_cbp_totals

        with _patch(
            "brewgis.workspace.services.lehd_fetcher.requests.get",
            side_effect=requests.RequestException("API down"),
        ):
            result = _compute_all_cbp_totals("06", "067", year=2011)
        assert result == {}

    def test_apply_cbp_county_scaling_scales_above_local(self) -> None:
        """_apply_cbp_county_scaling should scale up sub-sectors where CBP >> LEHD."""
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        from brewgis.workspace.services.lehd_fetcher import _ALL_SUB_COLUMNS
        from brewgis.workspace.services.lehd_fetcher import _SUBSECTOR_CBP_NAICS
        from brewgis.workspace.services.lehd_fetcher import _apply_cbp_county_scaling

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Determine the exact iteration order of cols_to_scale in the function
        cols_to_scale = [c for c in _ALL_SUB_COLUMNS if c in _SUBSECTOR_CBP_NAICS]
        # 16 sub-sector columns (all except emp_military)

        # Build scalar return sequence: [total_proxy, lodes_1, lodes_2, ..., lodes_16]
        scalar_values = [100000]  # total_proxy
        for col in cols_to_scale:
            if col == "emp_manufacturing":
                scalar_values.append(5000)  # LEHD total heavily suppressed
            else:
                scalar_values.append(80000)  # High enough to avoid scaling

        scalar_mock = MagicMock()
        scalar_mock.side_effect = scalar_values
        mock_conn.execute.return_value.scalar = scalar_mock

        # CBP totals: only manufacturing has CBP >> LEHD
        # All other columns: set CBP <= LEHD (80000) so they don't scale
        cbp_totals: dict[str, float] = {}
        for col in cols_to_scale:
            if col == "emp_manufacturing":
                cbp_totals[col] = 100000  # CBP >> LEHD (5000)
            else:
                cbp_totals[col] = 50000  # CBP < LEHD (80000) → no scaling

        with _patch(
            "brewgis.workspace.services.lehd_fetcher.get_engine",
            return_value=mock_engine,
        ):
            factors = _apply_cbp_county_scaling(cbp_totals)

        # Only manufacturing should have a scaling factor
        assert "emp_manufacturing" in factors
        assert factors["emp_manufacturing"] == 10.0
        # preserved_target = 100000 * 0.5 = 50000, scale_factor = 50000 / 5000 = 10.0

        # Other sub-sectors should NOT be in factors (CBP <= LEHD)
        for col in cols_to_scale:
            if col != "emp_manufacturing":
                assert col not in factors, f"{col} should not be scaled"


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
