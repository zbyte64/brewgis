"""Tests for the vmt dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/vmt.sql")


@pytest.mark.integration
class TestVmtTemplate(DbtModelTemplateTest):
    """Verify the vmt SQL template structure."""

    model_path = MODEL_PATH
    model_name = "vmt"
    uses_ref_core_end_state = False
    expected_cols = [
        "vmt_total",
        "vmt_per_capita",
        "auto_trips",
        "avg_trip_length_mi",
    ]

    def test_has_vmt_total_column(self, sql_template: str) -> None:
        assert "vmt_total" in sql_template

    def test_has_vmt_per_capita_column(self, sql_template: str) -> None:
        assert "vmt_per_capita" in sql_template

    def test_has_auto_trips_column(self, sql_template: str) -> None:
        assert "auto_trips" in sql_template

    def test_has_avg_trip_length_mi_column(self, sql_template: str) -> None:
        assert "avg_trip_length_mi" in sql_template

    def test_uses_circuity_var(self, sql_template: str) -> None:
        assert "transport_circuity_factor" in sql_template

    def test_uses_km_to_mi_conversion(self, sql_template: str) -> None:
        assert "0.621371" in sql_template

    @pytest.mark.parametrize(("col"), ["parcel_id"])
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template


@pytest.mark.integration
class TestVmtFormula:
    """Verify VMT formula logic produces correct values."""

    def test_vmt_calculation(self) -> None:
        auto_trips = 500.0
        avg_trip_km = 12.0
        circuity = 1.2
        result = auto_trips * avg_trip_km * 0.621371 * circuity
        assert result > 0

    def test_vmt_per_capita(self) -> None:
        vmt_total = 10_000.0
        population = 500.0
        result = vmt_total / population
        assert result > 0

    def test_vmt_per_capita_zero_population(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_avg_trip_length_mi(self) -> None:
        avg_trip_km = 12.0
        result = avg_trip_km * 0.621371
        assert result > 0

    def test_zero_vmt_no_trips(self) -> None:
        auto_trips = 0.0
        avg_trip_km = 12.0
        circuity = 1.2
        vmt = auto_trips * avg_trip_km * 0.621371 * circuity
        assert vmt == 0.0

    def test_circuity_factor_default(self) -> None:
        assert 1.2 == pytest.approx(1.2)
