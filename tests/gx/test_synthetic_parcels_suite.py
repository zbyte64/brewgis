"""Tests for the synthetic_parcels GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class SyntheticParcelsSuiteTest(TestCase):
    """Test that the synthetic_parcels suite is registered."""

    def test_suite_exists(self) -> None:
        """The synthetic_parcels suite is registered."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "synthetic_parcels" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The synthetic_parcels suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("synthetic_parcels")
        assert len(suite.expectations) > 0
