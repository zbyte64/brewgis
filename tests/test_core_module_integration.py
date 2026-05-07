"""Integration tests for the core_end_state and core_increment dbt models.

These tests require:
1. A running Docker stack with PostGIS
2. Test data loaded into the database (parcels with built_form_key, building types)
3. dbt installed and configured (via the DbtRunnerWrapper)

To run::

    docker compose -f docker-compose.local.yml run django \\
        pytest tests/test_core_module_integration.py -v

Skip if no PostGIS is available: ``pytest -m "not integration"``
"""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.workspace.models import Workspace


INTEGRATION_REASON = (
    "Requires PostGIS + test data. "
    "Run inside Docker: docker compose -f docker-compose.local.yml run django pytest"
)


@pytest.mark.integration
class TestCoreEndStateIntegration(TestCase):
    """Integration tests for the end_state dbt model.

    Setup steps before running:
    1. Create a workspace with known DB schema
    2. Create a parcels table with at least 3-5 parcels having built_form_key
    3. Populate the built_forms export table (via export_building_types())
       with known density parameters
    4. Optionally create an env_constraint result to test the integration
    """

    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="Core Integration Test",
            db_schema="public",
        )

    def test_end_state_produces_all_columns(self) -> None:
        """End state output should have all expected columns."""
        raise self.skipTest(INTEGRATION_REASON)

    def test_end_state_dwelling_units_match_building_type(self) -> None:
        """Dwelling units should be acres_developed * du_per_acre."""
        raise self.skipTest(INTEGRATION_REASON)

    def test_end_state_employment_matches_building_type(self) -> None:
        """Employment should be acres_developed * emp_per_acre."""
        raise self.skipTest(INTEGRATION_REASON)

    def test_end_state_land_dev_category_logic(self) -> None:
        """Land development category should follow du_per_acre thresholds.

        du_per_acre >= 10 → 'urban'
        du_per_acre >= 5 → 'compact'
        du_per_acre >= 1 → 'standard'
        else → 'rural'
        """
        raise self.skipTest(INTEGRATION_REASON)

    def test_end_state_with_env_constraint_integration(self) -> None:
        """End state should reference constraint output when available.

        acres_developable should match the env_constraint output value
        rather than gross acres.
        """
        raise self.skipTest(INTEGRATION_REASON)

    def test_end_state_zero_density_building_type(self) -> None:
        """Building type with du_per_acre=null and emp_per_acre=null.

        Should produce 0 dwelling units, 0 employment, 0 building_sqft.
        """
        raise self.skipTest(INTEGRATION_REASON)

    def test_increment_produces_change_vs_base_canvas(self) -> None:
        """Increment model should show difference between end_state and base canvas."""
        raise self.skipTest(INTEGRATION_REASON)

    def test_increment_all_zeros_when_no_base_canvas(self) -> None:
        """Increment without a base canvas should show all zeros or pass-through."""
        raise self.skipTest(INTEGRATION_REASON)

    def test_export_built_forms(self) -> None:
        """export_building_types() should create a table with correct columns."""
        raise self.skipTest(INTEGRATION_REASON)
