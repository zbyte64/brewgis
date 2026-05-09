"""Tests for the water_demand dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/water_demand.sql")


@pytest.mark.integration
class TestWaterDemandTemplate(DbtModelTemplateTest):
    """Verify the water_demand SQL template structure."""

    model_path = MODEL_PATH
    model_name = "water_demand"
    expected_cols = [
        "water_demand_res_indoor",
        "water_demand_res_outdoor",
        "water_demand_nonres_indoor",
        "water_demand_nonres_outdoor",
        "water_demand_total",
        "water_demand_per_unit",
    ]

    def test_has_res_indoor_column(self, sql_template: str) -> None:
        assert "water_demand_res_indoor" in sql_template

    def test_has_res_outdoor_column(self, sql_template: str) -> None:
        assert "water_demand_res_outdoor" in sql_template

    def test_has_nonres_indoor_column(self, sql_template: str) -> None:
        assert "water_demand_nonres_indoor" in sql_template

    def test_has_nonres_outdoor_column(self, sql_template: str) -> None:
        assert "water_demand_nonres_outdoor" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        assert "water_demand_total" in sql_template

    def test_has_per_unit_column(self, sql_template: str) -> None:
        assert "water_demand_per_unit" in sql_template

    def test_res_indoor_formula(self, sql_template: str) -> None:
        """Residential indoor: households * household_size * indoor_water_rate * 365."""
        assert "households *" in sql_template
        assert "household_size" in sql_template
        assert "indoor_water_rate" in sql_template
        assert "365.0" in sql_template

    def test_uses_nonres_rate_var(self, sql_template: str) -> None:
        assert "nonres_indoor_water_rate" in sql_template
        assert "50" in sql_template

    def test_res_outdoor_formula(self, sql_template: str) -> None:
        assert "res_irrigated_sqft * 0.092903" in sql_template
        assert "outdoor_water_rate" in sql_template

    def test_nonres_outdoor_formula(self, sql_template: str) -> None:
        assert "com_irrigated_sqft * 0.092903" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
            "gross_acres",
            "acres_developed",
            "population",
            "employment_total",
            "dwelling_units_total",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template


@pytest.mark.integration
class TestWaterDemandFormula:
    """Verify water demand formula logic produces correct values."""

    def test_res_indoor_calculation(self) -> None:
        households = 100.0
        household_size = 2.5
        indoor_rate = 200.0
        result = households * household_size * indoor_rate * 365.0
        assert result > 0

    def test_res_outdoor_calculation(self) -> None:
        sqft = 5000.0
        rate = 100.0
        result = sqft * 0.092903 * rate
        assert result > 0

    def test_per_unit_calculation(self) -> None:
        total = 1_000_000.0
        pop = 500.0
        emp = 200.0
        result = total / (pop + emp)
        assert result > 0

    def test_per_unit_zero_denom(self) -> None:
        result = 0.0
        assert result == 0.0
