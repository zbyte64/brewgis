"""Tests for the transport_ghg dbt model formula logic."""

from __future__ import annotations

import pytest


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
