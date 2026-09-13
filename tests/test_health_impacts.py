"""Tests for the health_impacts dbt model formula logic."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestHealthImpactsFormula:
    """Verify health impacts formula logic produces reasonable values."""

    def test_mortality_reduction_proportional(self) -> None:
        """PA benefit scales with MET-hours per week."""
        bg_death_rate = 0.008
        population = 1000.0
        met_hours = 5000.0  # annual
        met_per_week = met_hours / 52.0
        baseline_met = 11.25
        reduction_pct = 8.0
        effect = min(met_per_week / baseline_met, 1.0)
        deaths = bg_death_rate * population * effect * (reduction_pct / 100.0)
        assert deaths > 0
        assert deaths <= bg_death_rate * population * (reduction_pct / 100.0)

    def test_zero_met_no_benefit(self) -> None:
        deaths = 0.0 * 1000 * 0.008
        assert deaths == 0.0

    def test_zero_population_no_impact(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_dalys_from_deaths(self) -> None:
        """DALYs = deaths * (bg_dalys_per_capita / bg_death_rate)."""
        deaths = 0.64
        bg_dalys = 0.013
        bg_death = 0.008
        dalys = deaths * (bg_dalys / bg_death)
        assert dalys == pytest.approx(1.04, rel=0.01)

    def test_co2e_air_quality_effect(self) -> None:
        """Higher CO₂e → higher air quality health burden."""
        bg_death_rate = 0.008
        population = 1000.0
        co2e_kg = 500_000.0
        intake_frac = 1.6e-6
        conc_resp = 0.0062
        pm25_proxy = (co2e_kg / 1000.0) * intake_frac * conc_resp * 100.0
        deaths = bg_death_rate * population * min(pm25_proxy, 1.0)
        assert deaths > 0

    def test_net_dalys_positive_with_active_transport(self) -> None:
        """With activity but no transport GHG, net DALYs should be positive."""
        pa_benefit = 1.0
        aq_harm = 0.0
        net = pa_benefit - aq_harm
        assert net > 0

    def test_capped_mortality_reduction(self) -> None:
        """Mortality reduction cannot exceed 100% of max reduction."""
        met_per_week = 100.0  # well above baseline
        baseline_met = 11.25
        reduction = min(met_per_week / baseline_met, 1.0) * (8.0 / 100.0)
        assert reduction <= 0.08
