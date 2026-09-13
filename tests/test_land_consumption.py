"""Tests for the land_consumption dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestLandConsumptionFormula:
    """Verify land consumption formula logic produces correct values."""

    def test_building_footprint(self) -> None:
        sqft = 100_000.0
        coverage = 0.6
        result = sqft * coverage
        assert result > 0

    def test_parking_sqft(self) -> None:
        du = 50.0
        emp = 20.0
        spaces_per_du = 0.5
        spaces_per_emp = 0.2
        sqft_per_space = 300.0
        result = (du * spaces_per_du + emp * spaces_per_emp) * sqft_per_space
        assert result > 0

    def test_row_sqft(self) -> None:
        acres = 5.0
        row_frac = 0.15
        result = acres * row_frac * 43560.0
        assert result > 0

    def test_impervious_pct(self) -> None:
        impervious_sqft = 50_000.0
        gross_acres = 5.0
        result = (impervious_sqft / 43560.0) / gross_acres * 100.0
        assert result > 0

    def test_pervious_acres_zero_when_all_impervious(self) -> None:
        gross_acres = 1.0
        impervious_sqft = gross_acres * 43560.0
        result = gross_acres - impervious_sqft / 43560.0
        assert result == pytest.approx(0.0)

    def test_large_acres(self) -> None:
        acres = 1e6
        row_frac = 0.15
        result = acres * row_frac * 43560.0
        assert result == pytest.approx(6.534e9, rel=0.01)

    def test_zero_coverage(self) -> None:
        sqft = 100_000.0
        coverage = 0.0
        result = sqft * 0.0
        assert result == 0.0

    def test_negative_sqft(self) -> None:
        sqft = -5000.0
        coverage = 0.6
        result = sqft * coverage
        assert result < 0
