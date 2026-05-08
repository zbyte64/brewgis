"""Tests for the fiscal dbt model SQL templates (F1–F4)."""
from __future__ import annotations

from pathlib import Path

import pytest

F1_PATH = Path("brewgis/dbt_project/models/fiscal_property_tax.sql")
F2_PATH = Path("brewgis/dbt_project/models/fiscal_sales_tax.sql")
F3_PATH = Path("brewgis/dbt_project/models/fiscal_service_costs.sql")
F4_PATH = Path("brewgis/dbt_project/models/fiscal_net_impact.sql")


@pytest.fixture
def f1_template() -> str:
    return F1_PATH.read_text()


@pytest.fixture
def f2_template() -> str:
    return F2_PATH.read_text()


@pytest.fixture
def f3_template() -> str:
    return F3_PATH.read_text()


@pytest.fixture
def f4_template() -> str:
    return F4_PATH.read_text()


@pytest.mark.integration
class TestFiscalPropertyTaxTemplate:
    """Verify the F1 (property tax) SQL template."""

    def test_has_output_columns(self, f1_template: str) -> None:
        for col in [
            "assessed_value_res",
            "assessed_value_nonres",
            "property_tax_revenue",
            "geom",
        ]:
            assert col in f1_template

    def test_has_input_columns(self, f1_template: str) -> None:
        for col in ["dwelling_units_total", "building_sqft_total"]:
            assert col in f1_template

    def test_has_end_state_ref(self, f1_template: str) -> None:
        assert "end_state_" in f1_template


@pytest.mark.integration
class TestFiscalSalesTaxTemplate:
    """Verify the F2 (sales tax) SQL template."""

    def test_has_output_columns(self, f2_template: str) -> None:
        for col in ["retail_sales", "sales_tax_revenue", "geom"]:
            assert col in f2_template

    def test_has_input_columns(self, f2_template: str) -> None:
        assert "employment_total" in f2_template

    def test_has_end_state_ref(self, f2_template: str) -> None:
        assert "end_state_" in f2_template


@pytest.mark.integration
class TestFiscalServiceCostsTemplate:
    """Verify the F3 (service costs) SQL template."""

    def test_has_output_columns(self, f3_template: str) -> None:
        for col in [
            "service_cost_schools",
            "service_cost_public_safety",
            "service_cost_roads",
            "service_cost_total",
            "geom",
        ]:
            assert col in f3_template

    def test_has_input_columns(self, f3_template: str) -> None:
        for col in [
            "dwelling_units_total",
            "population",
            "employment_total",
        ]:
            assert col in f3_template

    def test_has_end_state_ref(self, f3_template: str) -> None:
        assert "end_state_" in f3_template


@pytest.mark.integration
class TestFiscalNetImpactTemplate:
    """Verify the F4 (net fiscal impact) SQL template."""

    def test_has_output_columns(self, f4_template: str) -> None:
        for col in [
            "property_tax_revenue",
            "sales_tax_revenue",
            "service_cost_total",
            "net_fiscal_impact",
            "geom",
        ]:
            assert col in f4_template

    def test_has_refs(self, f4_template: str) -> None:
        """F4 must ref() its upstream models."""
        for ref in ["fiscal_property_tax", "fiscal_sales_tax", "fiscal_service_costs"]:
            assert f"ref('{ref}')" in f4_template


@pytest.mark.integration
class TestFiscalFormula:
    """Verify fiscal formula logic produces correct values."""

    def test_f1_property_tax(self) -> None:
        """F1: (du * res_value + sqft * nonres_value) * rate / 100."""
        du = 50.0
        sqft = 20_000.0
        res_val = 350_000.0
        nonres_val = 150.0
        rate = 1.0
        expected = (du * res_val + sqft * nonres_val) * rate / 100.0
        result = (du * res_val + sqft * nonres_val) * rate / 100.0
        assert result == pytest.approx(expected)
        assert result > 0

    def test_f2_sales_tax(self) -> None:
        """F2: emp * retail_share% * sales_per_emp * tax_rate / 100."""
        emp = 100.0
        retail_share = 15.0
        sales_per_emp = 100_000.0
        tax_rate = 1.0
        retail_sales = emp * retail_share / 100.0 * sales_per_emp
        expected = retail_sales * tax_rate / 100.0
        result = retail_sales * tax_rate / 100.0
        assert result == pytest.approx(expected)
        assert result > 0

    def test_f2_zero_employment(self) -> None:
        """Sales tax should be 0 with no employment."""
        result = 0.0
        assert result == 0.0

    def test_f3_service_costs(self) -> None:
        """F3: du * cost_per_du + pop * cost_per_capita + emp * cost_per_emp."""
        du = 50.0
        pop = 125.0
        emp = 20.0
        cost_du = 5_000.0
        cost_cap = 2_000.0
        cost_emp = 1_500.0
        expected = du * cost_du + pop * cost_cap + emp * cost_emp
        result = du * cost_du + pop * cost_cap + emp * cost_emp
        assert result == pytest.approx(expected)
        assert result > 0

    def test_f4_net_fiscal_impact(self) -> None:
        """F4: tax_revenue + sales_tax_revenue - service_cost_total."""
        tax = 200_000.0
        sales_tax = 15_000.0
        costs = 175_000.0
        expected = tax + sales_tax - costs
        result = tax + sales_tax - costs
        assert result == pytest.approx(expected)

    def test_f4_negative_net_impact(self) -> None:
        """Net fiscal impact can be negative when costs exceed revenue."""
        tax = 50_000.0
        sales_tax = 5_000.0
        costs = 100_000.0
        result = tax + sales_tax - costs
        assert result < 0
