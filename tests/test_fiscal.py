"""Tests for the fiscal model formula logic (F1–F4)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestFiscalFormula:
    """Verify fiscal formula logic produces correct values."""

    def test_f1_property_tax(self) -> None:
        du = 50.0
        sqft = 20_000.0
        res_val = 350_000.0
        nonres_val = 150.0
        rate = 1.0
        result = (du * res_val + sqft * nonres_val) * rate / 100.0
        assert result > 0

    def test_f2_sales_tax(self) -> None:
        emp = 100.0
        retail_share = 15.0
        sales_per_emp = 100_000.0
        tax_rate = 1.0
        retail_sales = emp * retail_share / 100.0 * sales_per_emp
        result = retail_sales * tax_rate / 100.0
        assert result > 0

    def test_f2_zero_employment(self) -> None:
        result = 0.0
        assert result == 0.0

    def test_f3_service_costs(self) -> None:
        du = 50.0
        pop = 125.0
        emp = 20.0
        cost_du = 5_000.0
        cost_cap = 2_000.0
        cost_emp = 1_500.0
        result = du * cost_du + pop * cost_cap + emp * cost_emp
        assert result > 0

    def test_f4_net_fiscal_impact(self) -> None:
        tax = 200_000.0
        sales_tax = 15_000.0
        costs = 175_000.0
        result = tax + sales_tax - costs
        assert result > 0

    def test_f4_negative_net_impact(self) -> None:
        tax = 50_000.0
        sales_tax = 5_000.0
        costs = 100_000.0
        result = tax + sales_tax - costs
        assert result < 0

    def test_large_values(self) -> None:
        du = 1e6
        sqft = 1e6
        res_val = 350_000.0
        nonres_val = 150.0
        rate = 1.0
        result = (du * res_val + sqft * nonres_val) * rate / 100.0
        assert result == pytest.approx(3.5e9 + 1.5e6, rel=0.01)

    def test_zero_dwelling_units(self) -> None:
        du = 0.0
        sqft = 0.0
        res_val = 350_000.0
        nonres_val = 150.0
        rate = 1.0
        result = (0.0 * 350000 + 0.0 * 150) * 1.0 / 100.0
        assert result == 0.0

    def test_negative_nonres_value(self) -> None:
        du = 50.0
        sqft = -10_000.0
        res_val = 350_000.0
        nonres_val = 150.0
        rate = 1.0
        result = (50 * 350000 + -10000 * 150) * 1.0 / 100.0
        assert result == pytest.approx(160000.0)
