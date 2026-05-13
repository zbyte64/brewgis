"""Tests for the base_canvas GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class BaseCanvasSuiteTest(TestCase):
    """Test that the base_canvas expectation suite loads and runs."""

    def test_suite_exists(self) -> None:
        """The base_canvas suite is registered in the Data Context."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "base_canvas" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The base_canvas suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("base_canvas")
        assert len(suite.expectations) > 0
