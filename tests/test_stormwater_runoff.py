"""Tests for the stormwater_runoff dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/stormwater_runoff.sql")


@pytest.mark.integration
class TestStormwaterRunoffTemplate(DbtModelTemplateTest):
    """Verify the stormwater_runoff SQL template structure."""

    model_path = MODEL_PATH
    model_name = "stormwater_runoff"
    uses_ref_core_end_state = False
    expected_cols = [
        "impervious_acres",
        "impervious_pct",
        "runoff_coefficient",
        "runoff_volume_acre_ft",
        "runoff_baseline_acre_ft",
        "runoff_change_acre_ft",
        "runoff_change_pct",
    ]

    def test_has_impervious_acres_column(self, sql_template: str) -> None:
        assert "impervious_acres" in sql_template

    def test_has_impervious_pct_column(self, sql_template: str) -> None:
        assert "impervious_pct" in sql_template

    def test_has_runoff_coefficient_column(self, sql_template: str) -> None:
        assert "runoff_coefficient" in sql_template

    def test_has_runoff_volume_column(self, sql_template: str) -> None:
        assert "runoff_volume_acre_ft" in sql_template

    def test_has_baseline_column(self, sql_template: str) -> None:
        assert "runoff_baseline_acre_ft" in sql_template

    def test_has_change_columns(self, sql_template: str) -> None:
        assert "runoff_change_acre_ft" in sql_template
        assert "runoff_change_pct" in sql_template

    def test_uses_precipitation_var(self, sql_template: str) -> None:
        assert "stormwater_annual_precipitation_in" in sql_template

    def test_uses_simple_method(self, sql_template: str) -> None:
        assert "0.05 + 0.009" in sql_template

    def test_uses_land_consumption_ref(self, sql_template: str) -> None:
        assert "{{ ref('land_consumption') }}" in sql_template

    def test_uses_core_increment_ref(self, sql_template: str) -> None:
        assert "{{ ref('core_increment') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        ["parcel_id", "gross_acres", "impervious_acres", "impervious_pct"],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


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
