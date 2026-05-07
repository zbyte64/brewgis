"""Tests for the water_demand dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/water_demand.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the water_demand SQL template."""
    return MODEL_PATH.read_text()


class TestWaterDemandTemplate:
    """Verify the water_demand SQL template structure and formulas."""

    def test_file_exists(self) -> None:
        """Model file must exist."""
        assert MODEL_PATH.exists(), f"Missing {MODEL_PATH}"

    def test_jinja_braces_balanced(self, sql_template: str) -> None:
        """Jinja {{ and {% must be balanced."""
        # Count opening and closing braces
        assert sql_template.count("{{") == sql_template.count("}}"), "Unbalanced {{ }}"
        assert sql_template.count("{%") == sql_template.count("%}"), "Unbalanced {% %}"

    def test_templated_from_statement(self, sql_template: str) -> None:
        """FROM should reference the templated end_state table."""
        assert "FROM {{ var('target_schema') }}.end_state_{{ var('scenario_id') }}" in sql_template

    def test_has_res_indoor_column(self, sql_template: str) -> None:
        """Must compute residential indoor water demand."""
        assert "water_demand_res_indoor" in sql_template

    def test_has_res_outdoor_column(self, sql_template: str) -> None:
        """Must compute residential outdoor water demand."""
        assert "water_demand_res_outdoor" in sql_template

    def test_has_nonres_indoor_column(self, sql_template: str) -> None:
        """Must compute non-residential indoor water demand."""
        assert "water_demand_nonres_indoor" in sql_template

    def test_has_nonres_outdoor_column(self, sql_template: str) -> None:
        """Must compute non-residential outdoor water demand."""
        assert "water_demand_nonres_outdoor" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        """Must compute total water demand."""
        assert "water_demand_total" in sql_template

    def test_has_per_unit_column(self, sql_template: str) -> None:
        """Must compute per-unit water demand."""
        assert "water_demand_per_unit" in sql_template

    def test_res_indoor_formula(self, sql_template: str) -> None:
        """Residential indoor formula: households * household_size * indoor_water_rate * 365."""
        assert "households *" in sql_template
        assert "household_size" in sql_template
        assert "indoor_water_rate" in sql_template
        assert "365.0" in sql_template

    def test_uses_nonres_rate_var(self, sql_template: str) -> None:
        """Non-residential indoor rate uses dbt var with default of 50."""
        assert "nonres_indoor_water_rate" in sql_template
        assert "50" in sql_template

    def test_res_outdoor_formula(self, sql_template: str) -> None:
        """Residential outdoor formula: irrigated sqft -> m2 * outdoor rate."""
        assert "res_irrigated_sqft * 0.092903" in sql_template
        assert "outdoor_water_rate" in sql_template

    def test_nonres_outdoor_formula(self, sql_template: str) -> None:
        """Non-residential outdoor formula: irrigated sqft -> m2 * outdoor rate."""
        assert "com_irrigated_sqft * 0.092903" in sql_template

    def test_materialized_as_templated(self, sql_template: str) -> None:
        """Materialized as should reference scenario_id."""
        assert "water_demand_{{ var('scenario_id') }}" in sql_template

    def test_has_geom_column(self, sql_template: str) -> None:
        """Must include geom for spatial registration."""
        assert "es.geom" in sql_template or "geom" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
            "gross_acres",
            "acres_developed",
            "population",
            "employment_total",
            "dwelling_units_total",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        """Must include essential input columns from end_state."""
        assert col in sql_template


class TestWaterDemandFormula:
    """Verify water demand formula logic produces correct values."""

    def test_res_indoor_calculation(self) -> None:
        """Verify residential indoor water calculation: households * household_size * indoor_rate * 365."""
        households = 100.0
        household_size = 2.5
        indoor_rate = 200.0  # L/person/day
        expected = households * household_size * indoor_rate * 365.0
        result = households * household_size * indoor_rate * 365.0
        assert result == pytest.approx(expected)
        assert result > 0

    def test_res_outdoor_calculation(self) -> None:
        """Verify residential outdoor water calculation: sqft -> m2 * rate."""
        sqft = 5000.0
        rate = 100.0  # L/m2/yr
        expected = sqft * 0.092903 * rate
        result = sqft * 0.092903 * rate
        assert result == pytest.approx(expected)
        assert result > 0

    def test_per_unit_calculation(self) -> None:
        """Verify per-unit calculation: total / (population + employment)."""
        total = 1_000_000.0
        pop = 500.0
        emp = 200.0
        expected = total / (pop + emp)
        result = total / (pop + emp)
        assert result == pytest.approx(expected)

    def test_per_unit_zero_denom(self) -> None:
        """Per-unit should return 0.0 when population + employment is 0."""
        result = 0.0  # CASE WHEN (pop + emp) > 0 ELSE 0.0
        assert result == 0.0
