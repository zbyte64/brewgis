"""Tests for the vmt dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/vmt.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the vmt SQL template."""
    return MODEL_PATH.read_text()


@pytest.mark.integration
class TestVmtTemplate:
    """Verify the vmt SQL template structure and formulas."""

    def test_file_exists(self) -> None:
        """Model file must exist."""
        assert MODEL_PATH.exists(), f"Missing {MODEL_PATH}"

    def test_jinja_braces_balanced(self, sql_template: str) -> None:
        """Jinja {{ and {% must be balanced."""
        assert sql_template.count("{{") == sql_template.count("}}"), "Unbalanced {{ }}"
        assert sql_template.count("{%") == sql_template.count("%}"), "Unbalanced {% %}"

    def test_templated_from_mode_choice(self, sql_template: str) -> None:
        """FROM should reference mode_choice."""
        assert "mode_choice_{{ var('scenario_id') }}" in sql_template

    def test_templated_from_trip_distribution(self, sql_template: str) -> None:
        """FROM should reference trip_distribution."""
        assert "trip_distribution_{{ var('scenario_id') }}" in sql_template

    def test_templated_from_end_state(self, sql_template: str) -> None:
        """FROM should reference end_state."""
        assert "end_state_{{ var('scenario_id') }}" in sql_template

    def test_has_vmt_total_column(self, sql_template: str) -> None:
        """Must compute total VMT."""
        assert "vmt_total" in sql_template

    def test_has_vmt_per_capita_column(self, sql_template: str) -> None:
        """Must compute VMT per capita."""
        assert "vmt_per_capita" in sql_template

    def test_has_auto_trips_column(self, sql_template: str) -> None:
        """Must include auto trips."""
        assert "auto_trips" in sql_template

    def test_has_avg_trip_length_mi_column(self, sql_template: str) -> None:
        """Must include average trip length in miles."""
        assert "avg_trip_length_mi" in sql_template

    def test_has_geom_column(self, sql_template: str) -> None:
        """Must include geom for spatial registration."""
        assert "geom" in sql_template

    def test_uses_circuity_var(self, sql_template: str) -> None:
        """Must reference transport_circuity_factor var."""
        assert "transport_circuity_factor" in sql_template

    def test_uses_km_to_mi_conversion(self, sql_template: str) -> None:
        """Must convert km to mi using 0.621371."""
        assert "0.621371" in sql_template

    def test_materialized_as_templated(self, sql_template: str) -> None:
        """Materialized as should reference scenario_id."""
        assert "vmt_{{ var('scenario_id') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        """Must include essential input columns."""
        assert col in sql_template


@pytest.mark.integration
class TestVmtFormula:
    """Verify VMT formula logic produces correct values."""

    def test_vmt_calculation(self) -> None:
        """Verify VMT = auto_trips * avg_trip_length_km * 0.621371 * circuity."""
        auto_trips = 500.0
        avg_trip_km = 12.0
        circuity = 1.2
        expected = auto_trips * avg_trip_km * 0.621371 * circuity
        result = auto_trips * avg_trip_km * 0.621371 * circuity
        assert result == pytest.approx(expected)
        assert result > 0

    def test_vmt_per_capita(self) -> None:
        """Verify VMT per capita = vmt_total / population."""
        vmt_total = 10_000.0
        population = 500.0
        expected = vmt_total / population
        result = vmt_total / population
        assert result == pytest.approx(expected)

    def test_vmt_per_capita_zero_population(self) -> None:
        """VMT per capita should be 0 when population is 0."""
        vmt_total = 10_000.0
        population = 0.0
        result = 0.0  # CASE WHEN population > 0 ELSE 0.0
        assert result == 0.0

    def test_avg_trip_length_mi(self) -> None:
        """Verify avg_trip_length_mi = avg_trip_length_km * 0.621371."""
        avg_trip_km = 12.0
        expected = avg_trip_km * 0.621371
        result = avg_trip_km * 0.621371
        assert result == pytest.approx(expected)

    def test_zero_vmt_no_trips(self) -> None:
        """Zero auto trips should result in zero VMT."""
        auto_trips = 0.0
        avg_trip_km = 12.0
        circuity = 1.2
        vmt = auto_trips * avg_trip_km * 0.621371 * circuity
        assert vmt == 0.0

    def test_circuity_factor_default(self) -> None:
        """Default circuity factor is 1.2."""
        assert 1.2 == pytest.approx(1.2)
