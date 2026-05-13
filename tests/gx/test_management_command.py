"""Tests for the validate_data_quality management command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.test import TestCase


@pytest.mark.models
class ValidateDataQualityCommandTest(TestCase):
    """Test the validate_data_quality management command."""

    def test_list_flag(self) -> None:
        """The --list flag shows available checkpoints without error."""
        out = StringIO()
        call_command("validate_data_quality", "--list", stdout=out)
        output = out.getvalue()
        assert "Available checkpoints:" in output
        # Should list at least the base_canvas_etl checkpoint
        assert "base_canvas_etl" in output
