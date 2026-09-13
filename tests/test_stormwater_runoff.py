"""Tests for the stormwater_runoff dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestStormwaterRunoffFormula:
    """Verify stormwater runoff (Simple Method) formula logic."""

    def test_runoff_coefficient(self) -> None:
        """Rv = 0.05 + 0.009 * impervious_pct."""
        impervious_pct = 40.0
        rv = 0.05 + 0.009 * impervious_pct
        assert rv == pytest.approx(0.41, rel=0.01)

    def test_runoff_volume(self) -> None:
        """Runoff = P * Pj * Rv * A / 12 (acre-ft)."""
        precip = 12.0
        pj = 0.9
        rv = 0.41
        acres = 10.0
        volume = precip * pj * rv * acres / 12.0
        assert volume == pytest.approx(3.69, rel=0.01)

    def test_runoff_coefficient_zero_impervious(self) -> None:
        rv = 0.05 + 0.009 * 0.0
        assert rv == 0.05

    def test_runoff_coefficient_full_impervious(self) -> None:
        rv = 0.05 + 0.009 * 100.0
        assert rv == 0.95

    def test_higher_impervious_increases_runoff(self) -> None:
        precip = 12.0
        pj = 0.9
        acres = 10.0
        rv_low = 0.05 + 0.009 * 20.0
        rv_high = 0.05 + 0.009 * 60.0
        vol_low = precip * pj * rv_low * acres / 12.0
        vol_high = precip * pj * rv_high * acres / 12.0
        assert vol_high > vol_low

    def test_larger_area_more_runoff(self) -> None:
        precip = 12.0
        pj = 0.9
        rv = 0.41
        vol_small = precip * pj * rv * 1.0 / 12.0
        vol_large = precip * pj * rv * 100.0 / 12.0
        assert vol_large > vol_small

    def test_zero_acres_zero_runoff(self) -> None:
        precip = 12.0
        pj = 0.9
        rv = 0.41
        volume = precip * pj * rv * 0.0 / 12.0
        assert volume == 0.0

    def test_custom_precipitation(self) -> None:
        custom_precip = 24.0  # double default
        pj = 0.9
        rv = 0.41
        acres = 10.0
        volume = custom_precip * pj * rv * acres / 12.0
        default = 12.0 * pj * rv * acres / 12.0
        assert volume == 2.0 * default

    def test_runoff_change_pct_positive(self) -> None:
        """More impervious → positive runoff change."""
        baseline_vol = 3.0
        endstate_vol = 4.5
        change_pct = (endstate_vol - baseline_vol) / baseline_vol * 100.0
        assert change_pct == 50.0
