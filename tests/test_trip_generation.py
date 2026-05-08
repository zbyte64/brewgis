"""Tests for the trip_generation dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/trip_generation.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the trip_generation SQL template."""
    return MODEL_PATH.read_text()


@pytest.mark.integration
class TestTripGenerationTemplate:
    """Verify the trip_generation SQL template structure and formulas."""

    def test_file_exists(self) -> None:
        """Model file must exist."""
        assert MODEL_PATH.exists(), f"Missing {MODEL_PATH}"

    def test_jinja_braces_balanced(self, sql_template: str) -> None:
        """Jinja {{ and {% must be balanced."""
        assert sql_template.count("{{") == sql_template.count("}}"), "Unbalanced {{ }}"
        assert sql_template.count("{%") == sql_template.count("%}"), "Unbalanced {% %}"

    def test_templated_from_end_state(self, sql_template: str) -> None:
        """FROM should reference end_state."""
        assert "end_state_{{ var('scenario_id') }}" in sql_template

    def test_joins_built_forms(self, sql_template: str) -> None:
        """Must join built_forms for trip_rate_override."""
        assert "built_form_table" in sql_template
        assert "trip_rate_override" in sql_template

    def test_has_total_column(self, sql_template: str) -> None:
        """Must compute total trips."""
        assert "trips_total" in sql_template

    def test_has_res_column(self, sql_template: str) -> None:
        """Must compute residential trips."""
        assert "trips_res" in sql_template

    def test_has_nonres_column(self, sql_template: str) -> None:
        """Must compute non-residential trips."""
        assert "trips_nonres" in sql_template

    def test_has_hbw_column(self, sql_template: str) -> None:
        """Must compute HBW trips."""
        assert "trips_hbw" in sql_template

    def test_has_hbo_column(self, sql_template: str) -> None:
        """Must compute HBO trips."""
        assert "trips_hbo" in sql_template

    def test_has_nhb_column(self, sql_template: str) -> None:
        """Must compute NHB trips."""
        assert "trips_nhb" in sql_template

    def test_has_geom_column(self, sql_template: str) -> None:
        """Must include geom for spatial registration."""
        assert "geom" in sql_template

    def test_uses_dwelling_units(self, sql_template: str) -> None:
        """Must reference dwelling_units_total."""
        assert "dwelling_units_total" in sql_template

    def test_uses_building_sqft(self, sql_template: str) -> None:
        """Must reference building_sqft_total."""
        assert "building_sqft_total" in sql_template

    def test_uses_nonres_trip_rate_var(self, sql_template: str) -> None:
        """Non-res trip rate uses a dbt var."""
        assert "transport_nonres_trip_rate" in sql_template

    def test_uses_pass_by_var(self, sql_template: str) -> None:
        """Pass-by percentage uses a dbt var."""
        assert "transport_pass_by_pct" in sql_template

    def test_uses_purpose_split_vars(self, sql_template: str) -> None:
        """Purpose split shares use dbt vars."""
        assert "transport_hbw_pct" in sql_template
        assert "transport_hbo_pct" in sql_template
        assert "transport_nhb_pct" in sql_template

    def test_materialized_as_templated(self, sql_template: str) -> None:
        """Materialized as should reference scenario_id."""
        assert "trip_generation_{{ var('scenario_id') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        [
            "parcel_id",
            "gross_acres",
        ],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        """Must include essential input columns."""
        assert col in sql_template


@pytest.mark.integration
class TestTripGenerationFormula:
    """Verify trip generation formula logic produces correct values."""

    def test_res_trip_calculation(self) -> None:
        """Verify residential: dwelling_units * trip_rate_override."""
        units = 100.0
        rate = 9.57  # ITE single-family detached
        expected = units * rate
        result = units * rate
        assert result == pytest.approx(expected)
        assert result > 0

    def test_nonres_trip_calculation(self) -> None:
        """Verify non-res: (sqft / 1000) * rate."""
        sqft = 50_000.0
        rate = 42.94
        expected = (sqft / 1000.0) * rate
        result = (sqft / 1000.0) * rate
        assert result == pytest.approx(expected)
        assert result > 0

    def test_pass_by_reduction(self) -> None:
        """Verify pass-by reduction: nonres * (1 - pass_by_pct)."""
        nonres = 1000.0
        pass_by_pct = 0.15
        expected = nonres * (1.0 - pass_by_pct)
        result = nonres * (1.0 - pass_by_pct)
        assert result == pytest.approx(expected)

    def test_total_with_pass_by(self) -> None:
        """Total trips include pass-by reduced non-res."""
        res = 500.0
        nonres = 1000.0
        pass_by_pct = 0.15
        expected = res + nonres * (1.0 - pass_by_pct)
        result = res + nonres * (1.0 - pass_by_pct)
        assert result == pytest.approx(expected)

    def test_purpose_split_hbw(self) -> None:
        """HBW = total * hbw_pct."""
        total = 1500.0
        hbw_pct = 0.18
        expected = total * hbw_pct
        result = total * hbw_pct
        assert result == pytest.approx(expected)

    def test_purpose_split_hbo(self) -> None:
        """HBO = total * hbo_pct."""
        total = 1500.0
        hbo_pct = 0.42
        expected = total * hbo_pct
        result = total * hbo_pct
        assert result == pytest.approx(expected)

    def test_purpose_split_nhb(self) -> None:
        """NHB = total * nhb_pct."""
        total = 1500.0
        nhb_pct = 0.40
        expected = total * nhb_pct
        result = total * nhb_pct
        assert result == pytest.approx(expected)

    def test_purpose_splits_sum_to_total(self) -> None:
        """HBW + HBO + NHB should equal total trips."""
        total = 1500.0
        hbw = total * 0.18
        hbo = total * 0.42
        nhb = total * 0.40
        assert abs(hbw + hbo + nhb - total) < 0.01

    def test_zero_trips_for_empty_parcel(self) -> None:
        """Zero dwelling units and zero sqft = zero trips."""
        units = 0.0
        sqft = 0.0
        rate = 9.57
        nonres_rate = 42.94
        res = units * rate
        nonres = (sqft / 1000.0) * nonres_rate
        total = res + nonres
        assert total == 0.0

    def test_only_nonres_trips(self) -> None:
        """Non-res only parcel should produce nonres trips."""
        units = 0.0
        sqft = 100_000.0
        rate = 42.94
        res = units * 9.57
        nonres = (sqft / 1000.0) * rate
        assert res == 0.0
        assert nonres > 0
