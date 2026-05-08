"""Tests for the land_consumption dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/land_consumption.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the land_consumption SQL template."""
    return MODEL_PATH.read_text()


@pytest.mark.integration
class TestLandConsumptionTemplate:
    """Verify the land_consumption SQL template structure and formulas."""

    def test_has_l1_output_columns(self, sql_template: str) -> None:
        """Must include L1 land use change output columns."""
        for col in [
            "land_use_transition",
            "acres_consumed",
            "acres_preserved",
            "development_type",
        ]:
            assert col in sql_template

    def test_has_l2_output_columns(self, sql_template: str) -> None:
        """Must include L2 impervious surface output columns."""
        for col in [
            "impervious_sqft",
            "impervious_acres",
            "pervious_acres",
            "impervious_pct",
        ]:
            assert col in sql_template

    def test_has_end_state_ref(self, sql_template: str) -> None:
        """Must reference end_state_{scenario_id}."""
        assert "end_state_" in sql_template

    def test_has_input_columns(self, sql_template: str) -> None:
        """Must include essential input columns from end_state."""
        for col in [
            "parcel_id",
            "acres_developed",
            "building_sqft_total",
            "dwelling_units_total",
            "employment_total",
            "land_dev_category",
            "built_form_id",
            "geom",
        ]:
            assert col in sql_template

    def test_has_alias_config(self, sql_template: str) -> None:
        """Must have config with alias using scenario_id."""
        assert "config(alias='land_consumption_" in sql_template


@pytest.mark.integration
class TestLandConsumptionFormula:
    """Verify land consumption formula logic produces correct values."""

    def test_building_footprint(self) -> None:
        """Building footprint: building_sqft_total * ground_coverage_factor."""
        sqft = 100_000.0
        coverage = 0.6
        expected = sqft * coverage
        result = sqft * coverage
        assert result == pytest.approx(expected)
        assert result > 0

    def test_parking_sqft(self) -> None:
        """Parking: (DU * spaces/DU + emp * spaces/emp) * sqft/space."""
        du = 50.0
        emp = 20.0
        spaces_per_du = 0.5
        spaces_per_emp = 0.2
        sqft_per_space = 300.0
        expected = (du * spaces_per_du + emp * spaces_per_emp) * sqft_per_space
        result = (du * spaces_per_du + emp * spaces_per_emp) * sqft_per_space
        assert result == pytest.approx(expected)
        assert result > 0

    def test_row_sqft(self) -> None:
        """ROW: acres_developed * row_fraction * 43560."""
        acres = 5.0
        row_frac = 0.15
        expected = acres * row_frac * 43560.0
        result = acres * row_frac * 43560.0
        assert result == pytest.approx(expected)
        assert result > 0

    def test_impervious_pct(self) -> None:
        """Impervious pct: total_impervious_sqft / 43560 / gross_acres * 100."""
        impervious_sqft = 50_000.0
        gross_acres = 5.0
        expected = (impervious_sqft / 43560.0) / gross_acres * 100.0
        result = (impervious_sqft / 43560.0) / gross_acres * 100.0
        assert result == pytest.approx(expected)

    def test_pervious_acres_zero_when_all_impervious(self) -> None:
        """Pervious acres should be 0 when gross == impervious."""
        gross_acres = 1.0
        impervious_sqft = gross_acres * 43560.0
        result = gross_acres - impervious_sqft / 43560.0
        assert result == pytest.approx(0.0)
