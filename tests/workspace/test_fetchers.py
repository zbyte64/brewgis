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

        from brewgis.workspace.services.lehd_fetcher import CACHE_DIR
        from brewgis.workspace.services.lehd_fetcher import _compute_all_cbp_totals

        # Remove cached CBP data for 2011 so the API call is actually exercised.
        # Preceding tests may have written this cache file.
        cache_path = CACHE_DIR / "cbp_proportions" / "2011" / "06" / "067.json"
        if cache_path.exists():
            cache_path.unlink()

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
        """_compute_all_cbp_totals should raise RuntimeError when CBP API is unreachable."""
        from unittest.mock import patch as _patch

        import pytest
        import requests

        from brewgis.workspace.services.lehd_fetcher import CACHE_DIR
        from brewgis.workspace.services.lehd_fetcher import _compute_all_cbp_totals

        # Remove cached CBP data so the API call is exercised.
        cache_path = CACHE_DIR / "cbp_proportions" / "2011" / "06" / "067.json"
        if cache_path.exists():
            cache_path.unlink()

        with _patch(
            "brewgis.workspace.services.lehd_fetcher.requests.get",
            side_effect=requests.RequestException("API down"),
        ):
            with pytest.raises(RuntimeError):
                _compute_all_cbp_totals("06", "067", year=2011)

    # ── _compute_cbp_proportions Tests ────────────────────────────
    #
    # _compute_cbp_proportions is a pure function: raw CBP JSON data in,
    # proportions dict out.  No I/O, no mocks needed.

    def test_compute_cbp_proportions_math(self) -> None:
        """Proportions should sum to 1.0 within each parent group (goods, TTU, acc/food)."""
        from brewgis.workspace.services.lehd_fetcher import _compute_cbp_proportions

        raw_data = [
            ["EMP", "NAICS2017", "state", "county"],
            # Goods (CNS01): 11, 21, 23
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
            # TTU (CNS03): 22, 42, 44, 45, 48, 49
            ["4000", "22----", "06", "067"],
            ["8000", "42----", "06", "067"],
            ["12000", "44----", "06", "067"],
            ["5000", "45----", "06", "067"],
            ["15000", "48----", "06", "067"],
            ["3000", "49----", "06", "067"],
            # Acc/Food (CNS13): 721, 722
            ["7000", "721---", "06", "067"],
            ["25000", "722---", "06", "067"],
        ]
        result = _compute_cbp_proportions(raw_data)

        # CNS01: goods — 11+21+23 = 18000
        assert abs(result["11"] - 10000 / 18000) < 1e-4
        assert abs(result["21"] - 2000 / 18000) < 1e-4
        assert abs(result["23"] - 6000 / 18000) < 1e-4
        assert abs(result["11"] + result["21"] + result["23"] - 1.0) < 1e-4

        # CNS03: TTU — 22+42+44+45+48+49 = 47000
        assert abs(result["22"] - 4000 / 47000) < 1e-4
        assert abs(result["42"] - 8000 / 47000) < 1e-4
        assert abs(result["44"] - 12000 / 47000) < 1e-4
        assert abs(result["45"] - 5000 / 47000) < 1e-4
        assert abs(result["48"] - 15000 / 47000) < 1e-4
        assert abs(result["49"] - 3000 / 47000) < 1e-4
        cns03_sum = (
            result["22"]
            + result["42"]
            + result["44"]
            + result["45"]
            + result["48"]
            + result["49"]
        )
        assert abs(cns03_sum - 1.0) < 1e-4

        # CNS13: accommodation/food — 721+722 = 32000
        assert abs(result["721"] - 7000 / 32000) < 1e-4
        assert abs(result["722"] - 25000 / 32000) < 1e-4
        assert abs(result["721"] + result["722"] - 1.0) < 1e-4

    def test_compute_cbp_proportions_fallback_goods(self) -> None:
        """When goods employment data is empty, fallback proportions should be used."""
        from brewgis.workspace.services.lehd_fetcher import _compute_cbp_proportions

        raw_data = [
            ["EMP", "NAICS2017", "state", "county"],
            # TTU and acc/food only — no goods (11, 21, 23)
            ["4000", "22----", "06", "067"],
            ["8000", "42----", "06", "067"],
            ["7000", "721---", "06", "067"],
            ["25000", "722---", "06", "067"],
        ]
        result = _compute_cbp_proportions(raw_data)

        assert result["11"] == 0.05
        assert result["21"] == 0.02
        assert result["23"] == 0.93
        assert abs(result["11"] + result["21"] + result["23"] - 1.0) < 1e-4

        # TTU still computed from real data
        assert result["22"] > 0
        assert result["42"] > 0

    def test_compute_cbp_proportions_fallback_ttu(self) -> None:
        """When TTU employment data is empty, fallback proportions should be used."""
        from brewgis.workspace.services.lehd_fetcher import _compute_cbp_proportions

        raw_data = [
            ["EMP", "NAICS2017", "state", "county"],
            # Goods and acc/food only — no TTU (22, 42, 44, 45, 48, 49)
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
            ["7000", "721---", "06", "067"],
            ["25000", "722---", "06", "067"],
        ]
        result = _compute_cbp_proportions(raw_data)

        assert result["22"] == 0.02
        assert result["42"] == 0.10
        assert result["44"] == 0.54
        assert result["45"] == 0.28
        assert result["48"] == 0.04
        assert result["49"] == 0.02
        ttu_sum = (
            result["22"]
            + result["42"]
            + result["44"]
            + result["45"]
            + result["48"]
            + result["49"]
        )
        assert abs(ttu_sum - 1.0) < 1e-4
        assert abs(result["11"] - 10000 / 18000) < 1e-4

    def test_compute_cbp_proportions_fallback_accommodation_food(self) -> None:
        """When accommodation/food (721/722) data is empty, fallback proportions should be used."""
        from brewgis.workspace.services.lehd_fetcher import _compute_cbp_proportions

        raw_data = [
            ["EMP", "NAICS2017", "state", "county"],
            # Goods and TTU only — no acc/food (721, 722)
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
            ["4000", "22----", "06", "067"],
            ["8000", "42----", "06", "067"],
            ["12000", "44----", "06", "067"],
            ["5000", "45----", "06", "067"],
            ["15000", "48----", "06", "067"],
            ["3000", "49----", "06", "067"],
        ]
        result = _compute_cbp_proportions(raw_data)

        assert result["721"] == 0.4
        assert result["722"] == 0.6
        assert abs(result["721"] + result["722"] - 1.0) < 1e-4
        assert abs(result["11"] - 10000 / 18000) < 1e-4
        assert abs(result["22"] - 4000 / 47000) < 1e-4

    def test_compute_cbp_proportions_empty_data(self) -> None:
        """When only a header row is provided, should return empty dict."""
        from brewgis.workspace.services.lehd_fetcher import _compute_cbp_proportions

        result = _compute_cbp_proportions([["EMP", "NAICS2017", "state", "county"]])
        assert result == {}

    def test_build_cbp_proportions_cache_and_fetch(self) -> None:
        """Integration: orchestrator caches API response and reads from cache on second call."""
        import json
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        from brewgis.workspace.services.lehd_fetcher import CACHE_DIR
        from brewgis.workspace.services.lehd_fetcher import _build_cbp_proportions

        dl_path = CACHE_DIR / "cbp_proportions" / "2021" / "06" / "067.json"
        if dl_path.exists():
            dl_path.unlink()

        mock_get = MagicMock()
        mock_get.return_value.json.return_value = [
            ["EMP", "NAICS2017", "state", "county"],
            ["10000", "11----", "06", "067"],
            ["6000", "23----", "06", "067"],
            ["8000", "42----", "06", "067"],
        ]
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.status_code = 200

        with _patch("brewgis.workspace.services.lehd_fetcher.requests.get", mock_get):
            with _patch(
                "brewgis.workspace.services.lehd_fetcher._census_api_key",
                return_value="test_key",
            ):
                # First call — fetch from API and write cache
                r1 = _build_cbp_proportions("06", "067")
                assert mock_get.call_count == 1

                assert dl_path.exists()
                cached = json.loads(dl_path.read_text())
                assert cached[1][0] == "10000"

                # Second call — read from cache, no extra API call
                r2 = _build_cbp_proportions("06", "067")
                assert mock_get.call_count == 1  # still 1 — cache hit
                assert r1 == r2

                # Third call with ignore_cache — forces re-fetch
                mock_get.return_value.json.return_value = [
                    ["EMP", "NAICS2017", "state", "county"],
                    ["5000", "11----", "06", "067"],
                ]
                r3 = _build_cbp_proportions("06", "067", ignore_cache=True)
                assert mock_get.call_count == 2
                assert r3["11"] == 1.0


# ── POI Fetcher Tests ─────────────────────────────────────────────────


class TestParseCbpNaicsEmp:
    """Unit tests for _parse_cbp_naics_emp — CBP API response parser.

    The CBP API returns ``NAICS2017`` for year >= 2017 and ``NAICS2007``
    for year < 2017. The parser must handle both column names.
    """

    def test_normal_naics2017(self) -> None:
        """Parse a standard modern-year (>=2017) CBP response with NAICS2017 column."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 10000, "21": 2000, "23": 6000}

    def test_naics2007_column(self) -> None:
        """Parse a pre-2017 CBP response with NAICS2007 column.

        When year < 2017 the API returns NAICS2007 instead of NAICS2017.
        This is the format used by compare_sacog_basemap (LEHD_YEAR=2008).
        """
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "11----", "06", "067"],
            ["2000", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
        ]
        header = ["EMP", "NAICS2007", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        # CURRENT BUG: NAICS2007 rows are silently skipped because the
        # function hard-codes "NAICS2017". Result will be {} instead.
        assert result == {"11": 10000, "21": 2000, "23": 6000}

    def test_suppression_code_d(self) -> None:
        """Rows with EMP='D' (disclosure) should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "11----", "06", "067"],
            ["D", "21----", "06", "067"],
            ["6000", "23----", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 10000, "23": 6000}
        assert "21" not in result

    def test_suppression_code_s(self) -> None:
        """Rows with EMP='S' (suppressed) should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["S", "31----", "06", "067"], ["20000", "32----", "06", "067"]]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"32": 20000}

    def test_suppression_code_n(self) -> None:
        """Rows with EMP='N' (not available) should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["N", "31----", "06", "067"], ["50000", "33----", "06", "067"]]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"33": 50000}

    def test_empty_emp_skipped(self) -> None:
        """Rows with empty EMP string should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["", "11----", "06", "067"], ["5000", "21----", "06", "067"]]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"21": 5000}

    def test_empty_naics_skipped(self) -> None:
        """Rows with empty NAICS code should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "", "06", "067"],
            ["5000", "21----", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"21": 5000}

    def test_total_row_skipped(self) -> None:
        """The total row (NAICS code '------', all hyphens) should be skipped."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["100000", "------", "06", "067"],
            ["5000", "21----", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"21": 5000}

    def test_mixed_naics_lengths(self) -> None:
        """Parse 2-digit, 3-digit, and 6-digit NAICS codes correctly."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "11----", "06", "067"],
            ["7000", "721---", "06", "067"],
            ["25000", "722---", "06", "067"],
            ["8000", "311---", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 10000, "721": 7000, "722": 25000, "311": 8000}

    def test_zero_emp_kept(self) -> None:
        """Rows with EMP='0' should be kept (valid zero)."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["0", "11----", "06", "067"], ["5000", "21----", "06", "067"]]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 0, "21": 5000}

    def test_no_data_rows(self) -> None:
        """Empty rows list returns empty dict."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        result = _parse_cbp_naics_emp([], ["EMP", "NAICS2017", "state", "county"])
        assert result == {}

    def test_no_naics_column_in_header(self) -> None:
        """When neither NAICS2017 nor NAICS2007 exists in header, return empty dict."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["10000", "11----", "06", "067"]]
        header = ["EMP", "FIPS", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {}

    def test_row_shorter_than_header(self) -> None:
        """Row shorter than header should not crash (strict=False in zip)."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [["10000", "11----"]]  # missing state, county
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 10000}

    def test_strips_trailing_hyphens_and_spaces(self) -> None:
        """NAICS codes with hyphens and spaces are cleaned to just the prefix."""
        from brewgis.workspace.services.lehd_fetcher import _parse_cbp_naics_emp

        rows = [
            ["10000", "11-   ---", "06", "067"],
            ["5000", "  42     ", "06", "067"],
        ]
        header = ["EMP", "NAICS2017", "state", "county"]
        result = _parse_cbp_naics_emp(rows, header)
        assert result == {"11": 10000, "42": 5000}


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
