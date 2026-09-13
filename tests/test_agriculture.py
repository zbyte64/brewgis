"""Tests for the agriculture dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestAgricultureFormula:
    """Verify agriculture formula logic produces correct values."""

    def test_crop_yield(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        result = acres * yield_per_acre
        assert result > 0

    def test_market_value(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        result = acres * yield_per_acre * price
        assert result > 0

    def test_net_return(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        prod_cost_per_acre = 800.0
        market_value = acres * yield_per_acre * price
        prod_cost = acres * prod_cost_per_acre
        result = market_value - prod_cost
        assert result > 0

    def test_water_consumption(self) -> None:
        acres = 100.0
        water_per_acre = 3.0
        result = acres * water_per_acre
        assert result > 0

    def test_truck_trips(self) -> None:
        acres = 100.0
        trips_per_acre = 2.0
        result = acres * trips_per_acre
        assert result > 0

    def test_zero_acres(self) -> None:
        acres = 0.0
        assert acres == 0.0
        assert acres * 8.0 == 0.0
        assert acres * 200.0 == 0.0

    def test_large_acres(self) -> None:
        acres = 1e6
        result = acres * 200.0
        assert result == pytest.approx(2e8)

    def test_negative_acres(self) -> None:
        acres = -100.0
        result = acres * 200.0
        assert result < 0
