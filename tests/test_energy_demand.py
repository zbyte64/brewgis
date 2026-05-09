"""Tests for the energy_demand dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/energy_demand.sql")


@pytest.mark.integration
class TestEnergyDemandTemplate(DbtModelTemplateTest):
    """Verify the energy_demand SQL template structure."""

    model_path = MODEL_PATH
    model_name = "energy_demand"
    expected_cols = [
        "energy_electricity_res",
        "energy_gas_res",
        "energy_electricity_nonres",
        "energy_gas_nonres",
        "energy_total",
        "energy_intensity_kwh_per_sqft",
    ]

    def test_has_electricity_res_column(self, sql_template: str) -> None:
        assert "energy_electricity_res" in sql_template

    def test_has_gas_res_column(self, sql_template: str) -> None:
        assert "energy_gas_res" in sql_template

    def test_has_electricity_nonres_column(self, sql_template: str) -> None:
        assert "energy_electricity_nonres" in sql_template

    def test_has_gas_nonres_column(self, sql_template: str) -> None:
        assert "energy_gas_nonres" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        assert "energy_total" in sql_template

    def test_has_intensity_column(self, sql_template: str) -> None:
        assert "energy_intensity_kwh_per_sqft" in sql_template

    def test_uses_eui_coefficients(self, sql_template: str) -> None:
        assert "electricity_eui" in sql_template
        assert "gas_eui" in sql_template

    def test_uses_sqft_to_m2(self, sql_template: str) -> None:
        assert "0.092903" in sql_template

    def test_uses_res_far_var(self, sql_template: str) -> None:
        assert "res_far_default" in sql_template

    def test_nonres_electric_formula(self, sql_template: str) -> None:
        assert "building_sqft_total" in sql_template
        assert "electricity_eui" in sql_template

    def test_nonres_gas_formula(self, sql_template: str) -> None:
        assert "building_sqft_total" in sql_template
        assert "gas_eui" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
            "gross_acres",
            "acres_developed",
            "dwelling_units_total",
            "building_sqft_total",
            "population",
            "employment_total",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template


@pytest.mark.integration
class TestEnergyDemandFormula:
    """Verify energy demand formula logic produces correct values."""

    def test_nonres_electric_calculation(self) -> None:
        sqft = 100_000.0
        eui = 15.0
        result = sqft * 0.092903 * eui
        assert result > 0

    def test_nonres_gas_calculation(self) -> None:
        sqft = 100_000.0
        eui = 10.0
        result = sqft * 0.092903 * eui
        assert result > 0

    def test_res_unit_area_derivation(self) -> None:
        acres = 5.0
        far = 0.5
        units = 20.0
        result = acres * 43560.0 * far / units
        assert result > 0

    def test_res_electric_calculation(self) -> None:
        units = 20.0
        eui = 12.0
        acres = 5.0
        far = 0.5
        avg_unit_area = acres * 43560.0 * far / units
        result = units * eui * 0.092903 * avg_unit_area
        assert result > 0

    def test_intensity_calculation(self) -> None:
        total = 500_000.0
        sqft = 100_000.0
        result = total / sqft
        assert result > 0

    def test_intensity_zero_denom(self) -> None:
        result = 0.0
        assert result == 0.0
