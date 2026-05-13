"""Tests for the spatial_allocation GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class SpatialAllocationSuiteTest(TestCase):
    """Test that the spatial_allocation suite is registered."""

    def test_suite_exists(self) -> None:
        """The spatial_allocation suite is registered."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "spatial_allocation" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The spatial_allocation suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("spatial_allocation")
        assert len(suite.expectations) > 0
