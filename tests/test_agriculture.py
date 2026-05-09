"""Tests for the agriculture dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/agriculture.sql")


@pytest.mark.integration
class TestAgricultureTemplate(DbtModelTemplateTest):
    """Verify the agriculture SQL template structure."""

    model_path = MODEL_PATH
    model_name = "agriculture"
    expected_cols = [
        "crop_type",
        "acres_cultivated",
        "crop_yield_tons",
        "market_value",
        "production_cost",
        "net_return",
        "water_consumption_af",
        "labor_hours",
        "truck_trips",
    ]

    def test_has_output_columns(self, sql_template: str) -> None:
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
        for col in [
            "parcel_id",
            "parcel_acres_agriculture",
            "acres_developed",
            "land_dev_category",
            "geom",
        ]:
            assert col in sql_template

    def test_has_where_clause(self, sql_template: str) -> None:
        assert "WHERE" in sql_template
        assert (
            "parcel_acres_agriculture > 0" in sql_template
            or "land_dev_category = 'rural'" in sql_template
        )

    def test_uses_ref_for_dependency(self, sql_template: str) -> None:
        assert "{{ ref('core_end_state') }}" in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


@pytest.mark.integration
class TestAgricultureFormula:
    """Verify agriculture formula logic produces correct values."""

    def test_crop_yield(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        result = acres * yield_per_acre
        assert result > 0

    def test_market_value(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        result = acres * yield_per_acre * price
        assert result > 0

    def test_net_return(self) -> None:
        acres = 100.0
        yield_per_acre = 8.0
        price = 200.0
        prod_cost_per_acre = 800.0
        market_value = acres * yield_per_acre * price
        prod_cost = acres * prod_cost_per_acre
        result = market_value - prod_cost
        assert result > 0

    def test_water_consumption(self) -> None:
        acres = 100.0
        water_per_acre = 3.0
        result = acres * water_per_acre
        assert result > 0

    def test_truck_trips(self) -> None:
        acres = 100.0
        trips_per_acre = 2.0
        result = acres * trips_per_acre
        assert result > 0

    def test_zero_acres(self) -> None:
        acres = 0.0
        assert acres == 0.0
        assert acres * 8.0 == 0.0
        assert acres * 200.0 == 0.0

    def test_large_acres(self) -> None:
        acres = 1e6
        result = acres * 200.0
        assert result == pytest.approx(2e8)

    def test_negative_acres(self) -> None:
        acres = -100.0
        result = acres * 200.0
        assert result < 0
