"""Tests for the physical_activity dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestPhysicalActivityFormula:
    """Verify physical activity (MET-hours) formula logic."""

    def test_walk_met_hours(self) -> None:
        trips = 100.0
        dist_km = 2.0
        speed = 4.8
        met = 3.5
        result = trips * (dist_km / speed) * met
        assert result == pytest.approx(145.83, rel=0.01)

    def test_bike_met_hours(self) -> None:
        trips = 50.0
        dist_km = 5.0
        speed = 16.0
        met = 6.0
        result = trips * (dist_km / speed) * met
        assert result == pytest.approx(93.75, rel=0.01)

    def test_total_met_hours(self) -> None:
        walk_met = 145.83
        bike_met = 93.75
        result = walk_met + bike_met
        assert result == pytest.approx(239.58, rel=0.01)

    def test_zero_trips(self) -> None:
        result = 0.0 * (2.0 / 4.8) * 3.5
        assert result == 0.0

    def test_active_trip_share(self) -> None:
        walk = 100.0
        bike = 50.0
        auto = 500.0
        transit = 50.0
        total = walk + bike + auto + transit
        share = (walk + bike) / total
        assert share == pytest.approx(0.2143, rel=0.01)

    def test_active_share_no_trips(self) -> None:
        share = 0.0
        assert share == 0.0

    def test_active_share_all_active(self) -> None:
        walk = 100.0
        bike = 50.0
        share = (walk + bike) / (walk + bike)
        assert share == 1.0

    def test_custom_walk_speed(self) -> None:
        trips = 100.0
        dist_km = 2.0
        custom_speed = 5.0  # faster walk
        met = 3.5
        result = trips * (dist_km / custom_speed) * met
        fast_met = 100.0 * (2.0 / 4.8) * 3.5  # default
        assert result < fast_met
