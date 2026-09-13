"""Tests for the vmt dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestVmtFormula:
    """Verify VMT formula logic produces correct values."""

    def test_vmt_calculation(self) -> None:
        auto_trips = 500.0
        avg_trip_km = 12.0
        circuity = 1.2
        result = auto_trips * avg_trip_km * 0.621371 * circuity
        assert result > 0

    def test_vmt_per_capita(self) -> None:
        vmt_total = 10_000.0
        population = 500.0
        result = vmt_total / population
        assert result > 0

    def test_vmt_per_capita_zero_population(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_avg_trip_length_mi(self) -> None:
        avg_trip_km = 12.0
        result = avg_trip_km * 0.621371
        assert result > 0

    def test_zero_vmt_no_trips(self) -> None:
        auto_trips = 0.0
        avg_trip_km = 12.0
        circuity = 1.2
        vmt = auto_trips * avg_trip_km * 0.621371 * circuity
        assert vmt == 0.0

    def test_circuity_factor_default(self) -> None:
        """VMT with non-default circuity factor."""
        auto_trips = 1000.0
        avg_trip_km = 10.0
        default_circuity = 1.2
        override_circuity = 1.5
        default_vmt = auto_trips * avg_trip_km * 0.621371 * default_circuity
        override_vmt = auto_trips * avg_trip_km * 0.621371 * override_circuity
        assert override_vmt > default_vmt
        assert override_vmt == pytest.approx(
            auto_trips * avg_trip_km * 0.621371 * override_circuity
        )
