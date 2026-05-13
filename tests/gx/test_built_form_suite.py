"""Tests for the built_form_export GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class BuiltFormSuiteTest(TestCase):
    """Test that the built_form_export suite is registered."""

    def test_suite_exists(self) -> None:
        """The built_form_export suite is registered."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "built_form_export" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The built_form_export suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("built_form_export")
        assert len(suite.expectations) > 0
