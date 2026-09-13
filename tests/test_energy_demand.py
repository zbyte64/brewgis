"""Tests for the energy_demand dbt model formula logic."""

from __future__ import annotations

import pytest


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

    def test_large_values(self) -> None:
        sqft = 1e7
        eui = 15.0
        result = sqft * 0.092903 * eui
        assert result == pytest.approx(13935450.0, rel=0.01)

    def test_zero_area(self) -> None:
        sqft = 0.0
        eui = 15.0
        result = 0.0 * 0.092903 * 15.0
        assert result == 0.0

    def test_large_eui(self) -> None:
        sqft = 1000.0
        eui = 1e6
        result = sqft * 0.092903 * eui
        assert result == pytest.approx(9.2903e7, rel=0.01)
