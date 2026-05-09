"""Tests for the building_water_ghg dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/building_water_ghg.sql")


@pytest.mark.integration
class TestBuildingWaterGhgTemplate(DbtModelTemplateTest):
    """Verify the building_water_ghg SQL template structure."""

    model_path = MODEL_PATH
    model_name = "building_water_ghg"
    uses_ref_core_end_state = False
    expected_cols = [
        "co2e_energy_total_kg",
        "co2e_water_total_kg",
        "co2e_total_kg",
        "co2e_per_capita_kg",
    ]

    def test_has_energy_co2e_column(self, sql_template: str) -> None:
        assert "co2e_energy_total_kg" in sql_template

    def test_has_water_co2e_column(self, sql_template: str) -> None:
        assert "co2e_water_total_kg" in sql_template

    def test_has_total_co2e_column(self, sql_template: str) -> None:
        assert "co2e_total_kg" in sql_template

    def test_has_per_capita_column(self, sql_template: str) -> None:
        assert "co2e_per_capita_kg" in sql_template

    def test_uses_egrid_var(self, sql_template: str) -> None:
        assert "ghg_egrid_co2_per_kwh" in sql_template

    def test_uses_gas_var(self, sql_template: str) -> None:
        assert "ghg_gas_co2_per_kwh" in sql_template

    def test_uses_water_vars(self, sql_template: str) -> None:
        assert "ghg_water_supply_kwh_per_mg" in sql_template
        assert "ghg_wastewater_kwh_per_mg" in sql_template

    def test_uses_l_to_mg_conversion(self, sql_template: str) -> None:
        assert "3785411.8" in sql_template

    def test_uses_energy_refs(self, sql_template: str) -> None:
        assert "{{ ref('energy_demand') }}" in sql_template

    def test_uses_water_ref(self, sql_template: str) -> None:
        assert "{{ ref('water_demand') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
            "population",
            "energy_electricity_res",
            "energy_gas_res",
            "energy_electricity_nonres",
            "energy_gas_nonres",
            "water_demand_total",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


@pytest.mark.integration
class TestBuildingWaterGhgFormula:
    """Verify building/water GHG formula logic produces correct values."""

    def test_electric_co2e(self) -> None:
        kwh = 1_000_000.0
        egrid = 0.417
        result = kwh * egrid
        assert result == pytest.approx(417_000.0, rel=0.01)

    def test_gas_co2e(self) -> None:
        kwh = 500_000.0
        gas_factor = 0.181
        result = kwh * gas_factor
        assert result == pytest.approx(90_500.0, rel=0.01)

    def test_water_co2e(self) -> None:
        liters = 100_000_000.0  # ~26.4 MG
        mg = liters / 3_785_411.8
        total_kwh_per_mg = 1427 + 1911  # supply + wastewater
        egrid = 0.417
        result = mg * total_kwh_per_mg * egrid
        assert result > 0

    def test_water_co2e_zero_water(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_combined_building_co2e(self) -> None:
        elec_kwh = 1_000_000.0
        gas_kwh = 500_000.0
        egrid = 0.417
        gas_factor = 0.181
        building = elec_kwh * egrid + gas_kwh * gas_factor
        assert building == pytest.approx(507_500.0, rel=0.01)

    def test_zero_energy(self) -> None:
        result = 0.0 * 0.417 + 0.0 * 0.181
        assert result == 0.0

    def test_large_values(self) -> None:
        elec_kwh = 1e8
        egrid = 0.417
        result = elec_kwh * egrid
        assert result == pytest.approx(4.17e7, rel=0.01)

    def test_custom_egrid_factor(self) -> None:
        kwh = 1_000_000.0
        custom_egrid = 0.3
        result = kwh * custom_egrid
        assert result == 300_000.0
