"""Tests for the validate_data_quality management command."""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class ValidateDataQualityCommandTest(SimpleTestCase):
    """Test the validate_data_quality management command."""

    def test_list_contracts(self) -> None:
        out = io.StringIO()
        call_command("validate_data_quality", "--list", stdout=out)
        output = out.getvalue()
        assert "base_canvas" in output
        assert "census_acs" in output
        assert "lehd" in output
        assert "poi" in output
        assert "nlcd" in output
        assert "synthetic_parcels" in output
        assert "spatial_allocation" in output
        assert "column_stitching" in output
        assert "built_form_export" in output
        # dbt_module_run should be excluded from listing
        assert "dbt_module_run" not in output

    def test_missing_contract_raises_error(self) -> None:
        with pytest.raises(CommandError, match="No contracts match pattern"):
            call_command("validate_data_quality", "--contract", "nonexistent")
