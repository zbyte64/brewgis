"""Tests for the column_stitching GX expectation suite."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context


@pytest.mark.models
class ColumnStitchingSuiteTest(TestCase):
    """Test that the column_stitching suite is registered."""

    def test_suite_exists(self) -> None:
        """The column_stitching suite is registered."""
        context = get_gx_context()
        suites = context.list_expectation_suites()
        suite_names = [s.expectation_suite_name for s in suites]
        assert "column_stitching" in suite_names

    def test_suite_has_expectations(self) -> None:
        """The column_stitching suite has at least one expectation."""
        context = get_gx_context()
        suite = context.suites.get("column_stitching")
        assert len(suite.expectations) > 0
