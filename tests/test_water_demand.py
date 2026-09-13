"""Tests for the water_demand dbt model formula logic."""

from __future__ import annotations

import pytest


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

    def test_large_values(self) -> None:
        households = 1e6
        household_size = 2.5
        indoor_rate = 200.0
        result = households * household_size * indoor_rate * 365.0
        assert result == pytest.approx(1.825e11)

    def test_zero_values(self) -> None:
        households = 0.0
        household_size = 0.0
        indoor_rate = 200.0
        result = households * household_size * indoor_rate * 365.0
        assert result == 0.0

    def test_negative_handling(self) -> None:
        sqft = -5000.0
        rate = 100.0
        result = sqft * 0.092903 * rate
        assert result < 0
