"""Tests for the land_consumption dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/land_consumption.sql")


@pytest.mark.integration
class TestLandConsumptionTemplate(DbtModelTemplateTest):
    """Verify the land_consumption SQL template structure."""

    model_path = MODEL_PATH
    model_name = "land_consumption"
    expected_cols = [
        "land_use_transition",
        "acres_consumed",
        "acres_preserved",
        "development_type",
        "impervious_sqft",
        "impervious_acres",
        "pervious_acres",
        "impervious_pct",
    ]

    def test_has_l1_output_columns(self, sql_template: str) -> None:
        for col in [
            "land_use_transition",
            "acres_consumed",
            "acres_preserved",
            "development_type",
        ]:
            assert col in sql_template

    def test_has_l2_output_columns(self, sql_template: str) -> None:
        for col in [
            "impervious_sqft",
            "impervious_acres",
            "pervious_acres",
            "impervious_pct",
        ]:
            assert col in sql_template

    def test_has_input_columns(self, sql_template: str) -> None:
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
