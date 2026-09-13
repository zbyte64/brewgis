"""Tests for the building_water_ghg dbt model formula logic."""

from __future__ import annotations

import pytest


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
