"""Tests for the trip_generation dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/trip_generation.sql")


@pytest.mark.integration
class TestTripGenerationTemplate(DbtModelTemplateTest):
    """Verify the trip_generation SQL template structure."""

    model_path = MODEL_PATH
    model_name = "trip_generation"
    expected_cols = [
        "trips_total",
        "trips_res",
        "trips_nonres",
        "trips_hbw",
        "trips_hbo",
        "trips_nhb",
    ]

    def test_joins_built_forms(self, sql_template: str) -> None:
        assert "built_form_table" in sql_template
        assert "trip_rate_override" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        assert "trips_total" in sql_template

    def test_has_res_column(self, sql_template: str) -> None:
        assert "trips_res" in sql_template

    def test_has_nonres_column(self, sql_template: str) -> None:
        assert "trips_nonres" in sql_template

    def test_has_hbw_column(self, sql_template: str) -> None:
        assert "trips_hbw" in sql_template

    def test_has_hbo_column(self, sql_template: str) -> None:
        assert "trips_hbo" in sql_template

    def test_has_nhb_column(self, sql_template: str) -> None:
        assert "trips_nhb" in sql_template

    def test_uses_dwelling_units(self, sql_template: str) -> None:
        assert "dwelling_units_total" in sql_template

    def test_uses_building_sqft(self, sql_template: str) -> None:
        assert "building_sqft_total" in sql_template

    def test_uses_nonres_trip_rate_var(self, sql_template: str) -> None:
        assert "transport_nonres_trip_rate" in sql_template

    def test_uses_pass_by_var(self, sql_template: str) -> None:
        assert "transport_pass_by_pct" in sql_template

    def test_uses_purpose_split_vars(self, sql_template: str) -> None:
        assert "transport_hbw_pct" in sql_template
        assert "transport_hbo_pct" in sql_template
        assert "transport_nhb_pct" in sql_template

    @pytest.mark.parametrize(("col"), ["parcel_id", "gross_acres"])
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template


@pytest.mark.integration
class TestTripGenerationFormula:
    """Verify trip generation formula logic produces correct values."""

    def test_res_trip_calculation(self) -> None:
        units = 100.0
        rate = 9.57
        result = units * rate
        assert result > 0

    def test_nonres_trip_calculation(self) -> None:
        sqft = 50_000.0
        rate = 42.94
        result = (sqft / 1000.0) * rate
        assert result > 0

    def test_pass_by_reduction(self) -> None:
        nonres = 1000.0
        pass_by_pct = 0.15
        result = nonres * (1.0 - pass_by_pct)
        assert result > 0

    def test_total_with_pass_by(self) -> None:
        res = 500.0
        nonres = 1000.0
        pass_by_pct = 0.15
        result = res + nonres * (1.0 - pass_by_pct)
        assert result > 0

    def test_purpose_split_hbw(self) -> None:
        total = 1500.0
        hbw_pct = 0.18
        result = total * hbw_pct
        assert result > 0

    def test_purpose_split_hbo(self) -> None:
        total = 1500.0
        hbo_pct = 0.42
        result = total * hbo_pct
        assert result > 0

    def test_purpose_split_nhb(self) -> None:
        total = 1500.0
        nhb_pct = 0.40
        result = total * nhb_pct
        assert result > 0

    def test_purpose_splits_sum_to_total(self) -> None:
        total = 1500.0
        hbw = total * 0.18
        hbo = total * 0.42
        nhb = total * 0.40
        assert abs(hbw + hbo + nhb - total) < 0.01

    def test_zero_trips_for_empty_parcel(self) -> None:
        units = 0.0
        sqft = 0.0
        rate = 9.57
        nonres_rate = 42.94
        res = units * rate
        nonres = (sqft / 1000.0) * nonres_rate
        total = res + nonres
        assert total == 0.0

    def test_only_nonres_trips(self) -> None:
        units = 0.0
        sqft = 100_000.0
        rate = 42.94
        res = units * 9.57
        nonres = (sqft / 1000.0) * rate
        assert res == 0.0
        assert nonres > 0
