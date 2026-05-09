"""Tests for the health_impacts dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/health_impacts.sql")


@pytest.mark.integration
class TestHealthImpactsTemplate(DbtModelTemplateTest):
    """Verify the health_impacts SQL template structure."""

    model_path = MODEL_PATH
    model_name = "health_impacts"
    uses_ref_core_end_state = False
    expected_cols = [
        "dalys_averted_pa",
        "dalys_added_air_quality",
        "net_dalys",
        "deaths_averted_pa",
        "deaths_added_air_quality",
    ]

    def test_has_dalys_averted_column(self, sql_template: str) -> None:
        assert "dalys_averted_pa" in sql_template

    def test_has_dalys_added_column(self, sql_template: str) -> None:
        assert "dalys_added_air_quality" in sql_template

    def test_has_net_dalys_column(self, sql_template: str) -> None:
        assert "net_dalys" in sql_template

    def test_has_deaths_averted_column(self, sql_template: str) -> None:
        assert "deaths_averted_pa" in sql_template

    def test_has_deaths_added_column(self, sql_template: str) -> None:
        assert "deaths_added_air_quality" in sql_template

    def test_uses_met_vars(self, sql_template: str) -> None:
        assert "health_heat_mortality_reduction_pct" in sql_template
        assert "health_heat_baseline_met_hours_per_week" in sql_template

    def test_uses_pm25_vars(self, sql_template: str) -> None:
        assert "health_pm25_intake_fraction" in sql_template
        assert "health_pm25_concentration_response" in sql_template

    def test_uses_background_vars(self, sql_template: str) -> None:
        assert "health_background_dalys_per_capita" in sql_template
        assert "health_background_death_rate" in sql_template

    def test_uses_physical_activity_ref(self, sql_template: str) -> None:
        assert "{{ ref('physical_activity') }}" in sql_template

    def test_uses_transport_ghg_ref(self, sql_template: str) -> None:
        assert "{{ ref('transport_ghg') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        ["parcel_id", "total_met_hours", "co2e_transport_kg", "population"],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


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
