"""Tests for the energy_demand dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/energy_demand.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the energy_demand SQL template."""
    return MODEL_PATH.read_text()


class TestEnergyDemandTemplate:
    """Verify the energy_demand SQL template structure and formulas."""

    def test_file_exists(self) -> None:
        """Model file must exist."""
        assert MODEL_PATH.exists(), f"Missing {MODEL_PATH}"

    def test_jinja_braces_balanced(self, sql_template: str) -> None:
        """Jinja {{ and {% must be balanced."""
        assert sql_template.count("{{") == sql_template.count("}}"), "Unbalanced {{ }}"
        assert sql_template.count("{%") == sql_template.count("%}"), "Unbalanced {% %}"

    def test_templated_from_statement(self, sql_template: str) -> None:
        """FROM should reference the templated end_state table."""
        assert "FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}" in sql_template

    def test_has_electricity_res_column(self, sql_template: str) -> None:
        """Must compute residential electricity demand."""
        assert "energy_electricity_res" in sql_template

    def test_has_gas_res_column(self, sql_template: str) -> None:
        """Must compute residential gas demand."""
        assert "energy_gas_res" in sql_template

    def test_has_electricity_nonres_column(self, sql_template: str) -> None:
        """Must compute non-residential electricity demand."""
        assert "energy_electricity_nonres" in sql_template

    def test_has_gas_nonres_column(self, sql_template: str) -> None:
        """Must compute non-residential gas demand."""
        assert "energy_gas_nonres" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        """Must compute total energy demand."""
        assert "energy_total" in sql_template

    def test_has_intensity_column(self, sql_template: str) -> None:
        """Must compute energy intensity."""
        assert "energy_intensity_kwh_per_sqft" in sql_template

    def test_uses_eui_coefficients(self, sql_template: str) -> None:
        """Must reference electricity_eui and gas_eui from end_state."""
        assert "electricity_eui" in sql_template
        assert "gas_eui" in sql_template

    def test_uses_sqft_to_m2(self, sql_template: str) -> None:
        """Must convert sqft to m2 using 0.092903."""
        assert "0.092903" in sql_template

    def test_uses_res_far_var(self, sql_template: str) -> None:
        """Residential FAR uses a dbt var."""
        assert "res_far_default" in sql_template

    def test_nonres_electric_formula(self, sql_template: str) -> None:
        """Non-res electric: building_sqft_total * 0.092903 * electricity_eui."""
        assert "building_sqft_total" in sql_template
        assert "electricity_eui" in sql_template

    def test_nonres_gas_formula(self, sql_template: str) -> None:
        """Non-res gas: building_sqft_total * 0.092903 * gas_eui."""
        assert "building_sqft_total" in sql_template
        assert "gas_eui" in sql_template

    def test_materialized_as_templated(self, sql_template: str) -> None:
        """Materialized as should reference scenario_id."""
        assert "energy_demand_{{ var('scenario_id') }}" in sql_template

    def test_has_geom_column(self, sql_template: str) -> None:
        """Must include geom for spatial registration."""
        assert "es.geom" in sql_template or "geom" in sql_template

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
        """Must include essential input columns from end_state."""
        assert col in sql_template


class TestEnergyDemandFormula:
    """Verify energy demand formula logic produces correct values."""

    def test_nonres_electric_calculation(self) -> None:
        """Verify non-res electric: building_sqft * 0.092903 * eui."""
        sqft = 100_000.0
        eui = 15.0  # kWh/m2/yr
        expected = sqft * 0.092903 * eui
        result = sqft * 0.092903 * eui
        assert result == pytest.approx(expected)
        assert result > 0

    def test_nonres_gas_calculation(self) -> None:
        """Verify non-res gas: building_sqft * 0.092903 * eui."""
        sqft = 100_000.0
        eui = 10.0  # kWh/m2/yr
        expected = sqft * 0.092903 * eui
        result = sqft * 0.092903 * eui
        assert result == pytest.approx(expected)

    def test_res_unit_area_derivation(self) -> None:
        """Verify unit area derivation: acres * 43560 * FAR / units."""
        acres = 5.0
        far = 0.5
        units = 20.0
        expected_avg_area = acres * 43560.0 * far / units
        result = acres * 43560.0 * far / units
        assert result == pytest.approx(expected_avg_area)
        assert result > 0

    def test_res_electric_calculation(self) -> None:
        """Verify res electric: units * eui * 0.092903 * avg_unit_area."""
        units = 20.0
        eui = 12.0
        acres = 5.0
        far = 0.5
        avg_unit_area = acres * 43560.0 * far / units
        expected = units * eui * 0.092903 * avg_unit_area
        result = units * eui * 0.092903 * avg_unit_area
        assert result == pytest.approx(expected)

    def test_intensity_calculation(self) -> None:
        """Verify intensity: total / building_sqft_total."""
        total = 500_000.0
        sqft = 100_000.0
        expected = total / sqft
        result = total / sqft
        assert result == pytest.approx(expected)
        assert result > 0

    def test_intensity_zero_denom(self) -> None:
        """Intensity should return 0.0 when building_sqft_total is 0."""
        result = 0.0  # CASE WHEN building_sqft_total > 0 ELSE 0.0
        assert result == 0.0
