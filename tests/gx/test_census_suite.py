"""Tests for the census_acs_staging GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class CensusSuiteTest(TestCase):
    """Test that the census_acs_staging suite is registered."""

    def test_suite_exists(self) -> None:
        """The census_acs_staging suite is registered."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "census_acs_staging" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The census_acs_staging suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("census_acs_staging")
        assert len(suite.expectations) > 0
