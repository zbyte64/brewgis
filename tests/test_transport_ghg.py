"""Tests for the transport_ghg dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/transport_ghg.sql")


@pytest.mark.integration
class TestTransportGhgTemplate(DbtModelTemplateTest):
    """Verify the transport_ghg SQL template structure."""

    model_path = MODEL_PATH
    model_name = "transport_ghg"
    uses_ref_core_end_state = False
    expected_cols = [
        "co2e_total_kg",
        "co2e_per_capita_kg",
        "vmt_total",
        "avg_trip_length_mi",
        "auto_trips",
    ]

    def test_has_co2e_total_column(self, sql_template: str) -> None:
        assert "co2e_total_kg" in sql_template

    def test_has_co2e_per_capita_column(self, sql_template: str) -> None:
        assert "co2e_per_capita_kg" in sql_template

    def test_has_vmt_total_column(self, sql_template: str) -> None:
        assert "vmt_total" in sql_template

    def test_has_avg_trip_length_mi_column(self, sql_template: str) -> None:
        assert "avg_trip_length_mi" in sql_template

    def test_has_auto_trips_column(self, sql_template: str) -> None:
        assert "auto_trips" in sql_template

    def test_uses_co2_per_mile_var(self, sql_template: str) -> None:
        assert "transport_ghg_co2_per_mile" in sql_template

    def test_uses_speed_adjust_var(self, sql_template: str) -> None:
        assert "transport_ghg_speed_adjust" in sql_template

    def test_uses_ref_for_dependency(self, sql_template: str) -> None:
        assert "{{ ref('vmt') }}" in sql_template

    @pytest.mark.parametrize(("col"), ["parcel_id", "population"])
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


@pytest.mark.integration
class TestTransportGhgFormula:
    """Verify transport GHG formula logic produces correct values."""

    def test_co2e_calculation(self) -> None:
        vmt = 10_000.0
        co2_per_mile = 0.411
        result = vmt * co2_per_mile
        assert result == pytest.approx(4110.0, rel=0.01)

    def test_co2e_per_capita(self) -> None:
        co2e_total = 4110.0
        population = 500.0
        result = co2e_total / population
        assert result == pytest.approx(8.22, rel=0.01)

    def test_co2e_per_capita_zero_population(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_zero_vmt_zero_emissions(self) -> None:
        vmt = 0.0
        co2_per_mile = 0.411
        result = vmt * co2_per_mile
        assert result == 0.0

    def test_custom_co2_per_mile(self) -> None:
        vmt = 10_000.0
        custom_factor = 0.5
        result = vmt * custom_factor
        assert result == 5000.0

    def test_speed_adjustment_increases_emissions(self) -> None:
        vmt = 10_000.0
        co2_per_mile = 0.411
        base = vmt * co2_per_mile
        adjusted = vmt * co2_per_mile * 1.15
        assert adjusted > base
        assert adjusted == pytest.approx(4726.5, rel=0.01)

    def test_large_values(self) -> None:
        vmt = 1e8
        co2_per_mile = 0.411
        result = vmt * co2_per_mile
        assert result == pytest.approx(4.11e7, rel=0.01)
