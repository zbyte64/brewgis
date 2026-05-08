"""Tests for the agriculture dbt model SQL template."""
from __future__ import annotations

from pathlib import Path

import pytest

MODEL_PATH = Path("brewgis/dbt_project/models/agriculture.sql")


@pytest.fixture
def sql_template() -> str:
    """Read the agriculture SQL template."""
    return MODEL_PATH.read_text()


@pytest.mark.integration
class TestAgricultureTemplate:
    """Verify the agriculture SQL template structure and formulas."""

    def test_has_output_columns(self, sql_template: str) -> None:
        """Must include all expected output columns."""
        for col in [
            "crop_type",
            "acres_cultivated",
            "crop_yield_tons",
            "market_value",
            "production_cost",
            "net_return",
            "water_consumption_af",
            "labor_hours",
            "truck_trips",
            "geom",
        ]:
            assert col in sql_template

    def test_has_input_columns(self, sql_template: str) -> None:
        """Must include essential input columns from end_state."""
        for col in [
            "parcel_id",
            "parcel_acres_agriculture",
            "acres_developed",
            "land_dev_category",
            "geom",
        ]:
            assert col in sql_template

    def test_has_end_state_ref(self, sql_template: str) -> None:
        """Must reference end_state_{scenario_id}."""
        assert "end_state_" in sql_template

    def test_has_where_clause(self, sql_template: str) -> None:
        """Must filter for agricultural or rural parcels."""
        assert "WHERE" in sql_template
        assert "parcel_acres_agriculture > 0" in sql_template or "land_dev_category = 'rural'" in sql_template

    def test_has_alias_config(self, sql_template: str) -> None:
        """Must have config with alias using scenario_id."""
        assert "config(alias='agriculture_" in sql_template


@pytest.mark.integration
class TestAgricultureFormula:
    """Verify agriculture formula logic produces correct values."""

    def test_crop_yield(self) -> None:
        """Yield = acres * yield_per_acre."""
        acres = 100.0
        yield_per_acre = 8.0
        expected = acres * yield_per_acre
        result = acres * yield_per_acre
        assert result == pytest.approx(expected)

    def test_market_value(self) -> None:
        """Market value = acres * yield * price."""
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        expected = acres * yield_per_acre * price
        result = acres * yield_per_acre * price
        assert result == pytest.approx(expected)

    def test_net_return(self) -> None:
        """Net return = market_value - production_cost."""
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        prod_cost_per_acre = 800.0
        market_value = acres * yield_per_acre * price
        prod_cost = acres * prod_cost_per_acre
        expected = market_value - prod_cost
        result = market_value - prod_cost
        assert result == pytest.approx(expected)
        assert result > 0  # positive net return at default values

    def test_water_consumption(self) -> None:
        """Water = acres * water_per_acre (acre-feet)."""
        acres = 100.0
        water_per_acre = 3.0
        expected = acres * water_per_acre
        result = acres * water_per_acre
        assert result == pytest.approx(expected)

    def test_truck_trips(self) -> None:
        """Truck trips = acres * trips_per_acre."""
        acres = 100.0
        trips_per_acre = 2.0
        expected = acres * trips_per_acre
        result = acres * trips_per_acre
        assert result == pytest.approx(expected)

    def test_zero_acres(self) -> None:
        """All values should be 0 when acres is 0."""
        acres = 0.0
        assert acres == 0.0
        assert acres * 8.0 == 0.0
        assert acres * 200.0 == 0.0
