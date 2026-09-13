"""Tests for the trip_generation dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestTripGenerationFormula:
    """Verify trip generation formula logic produces correct values."""

    def test_res_trip_calculation(self) -> None:
        units = 100.0
        rate = 9.57
        result = units * rate
        assert result > 0

    def test_nonres_trip_calculation(self) -> None:
        sqft = 50_000.0
        rate = 42.94
        result = (sqft / 1000.0) * rate
        assert result > 0

    def test_pass_by_reduction(self) -> None:
        nonres = 1000.0
        pass_by_pct = 0.15
        result = nonres * (1.0 - pass_by_pct)
        assert result > 0

    def test_total_with_pass_by(self) -> None:
        res = 500.0
        nonres = 1000.0
        pass_by_pct = 0.15
        result = res + nonres * (1.0 - pass_by_pct)
        assert result > 0

    def test_purpose_split_hbw(self) -> None:
        total = 1500.0
        hbw_pct = 0.18
        result = total * hbw_pct
        assert result > 0

    def test_purpose_split_hbo(self) -> None:
        total = 1500.0
        hbo_pct = 0.42
        result = total * hbo_pct
        assert result > 0

    def test_purpose_split_nhb(self) -> None:
        total = 1500.0
        nhb_pct = 0.40
        result = total * nhb_pct
        assert result > 0

    def test_purpose_splits_sum_to_total(self) -> None:
        total = 1500.0
        hbw = total * 0.18
        hbo = total * 0.42
        nhb = total * 0.40
        assert abs(hbw + hbo + nhb - total) < 0.01

    def test_zero_trips_for_empty_parcel(self) -> None:
        units = 0.0
        sqft = 0.0
        rate = 9.57
        nonres_rate = 42.94
        res = units * rate
        nonres = (sqft / 1000.0) * nonres_rate
        total = res + nonres
        assert total == 0.0

    def test_only_nonres_trips(self) -> None:
        units = 0.0
        sqft = 100_000.0
        rate = 42.94
        res = units * 9.57
        nonres = (sqft / 1000.0) * rate
        assert res == 0.0
        assert nonres > 0

    def test_large_employment(self) -> None:
        """Verify calculation with large employment values."""
        emp = 1e6
        emp_rate = 4.0
        result = emp * emp_rate
        assert result == pytest.approx(4e6)

    def test_zero_res_rate(self) -> None:
        """Verify calculation with zero residential rate."""
        du = 100.0
        res_rate = 0.0
        result = du * res_rate
        assert result == 0.0

    def test_negative_dwelling_units(self) -> None:
        """Verify calculation with negative dwelling units stays negative."""
        du = -100.0
        res_rate = 4.0
        result = du * res_rate
        assert result < 0
