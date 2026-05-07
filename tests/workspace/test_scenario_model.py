# ruff: noqa: ANN001, ANN201
"""Tests for the Scenario model."""

from __future__ import annotations

import pytest

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from brewgis.workspace.models import Scenario, ScenarioType

from tests.factories import ScenarioFactory, WorkspaceFactory


@pytest.mark.models
class TestScenarioModel(TestCase):
    """Tests for the Scenario model fields and methods."""

    def setUp(self) -> None:
        self.scenario = ScenarioFactory(
            name="Test Scenario",
            slug="test-scenario",
            base_year=2020,
            horizon_year=2050,
        )

    def test_str(self) -> None:
        """__str__ should return the scenario name."""
        self.assertEqual(str(self.scenario), "Test Scenario")

    def test_target_schema(self) -> None:
        """target_schema should return 'scenario_{slug}'."""
        self.assertEqual(self.scenario.target_schema, "scenario_test-scenario")

    def test_default_scenario_type(self) -> None:
        """Default scenario_type should be 'base'."""
        s = ScenarioFactory()
        self.assertEqual(s.scenario_type, ScenarioType.BASE)

    def test_scenario_type_alternative(self) -> None:
        """scenario_type can be set to 'alternative'."""
        s = ScenarioFactory(scenario_type="alternative")
        self.assertEqual(s.scenario_type, "alternative")

    def test_parent_nullable(self) -> None:
        """parent FK should be nullable."""
        self.assertIsNone(self.scenario.parent)

    def test_parent_set_to_base(self) -> None:
        """Alternative scenario can reference a base scenario as parent."""
        base = ScenarioFactory(scenario_type="base")
        alt = ScenarioFactory(scenario_type="alternative", parent=base)
        self.assertEqual(alt.parent, base)
        self.assertIn(alt, base.alternatives.all())

    def test_auto_slug_on_save(self) -> None:
        """Slug should be auto-generated from name if not provided."""
        s = ScenarioFactory(name="My New Scenario", slug="")
        s.save()
        self.assertEqual(s.slug, "my-new-scenario")
    def test_workspace_fk(self) -> None:
        """Scenario should belong to a workspace."""
        ws = WorkspaceFactory()
        s = ScenarioFactory(workspace=ws)
        self.assertEqual(s.workspace, ws)

    def test_workspace_scenarios_related_name(self) -> None:
        """Workspace should have a scenarios related name."""
        ws = WorkspaceFactory()
        s1 = ScenarioFactory(workspace=ws)
        s2 = ScenarioFactory(workspace=ws)
        self.assertIn(s1, ws.scenarios.all())
        self.assertIn(s2, ws.scenarios.all())

    def test_unique_together_workspace_slug(self) -> None:
        """Duplicate slug in same workspace should raise IntegrityError."""
        from django.db.utils import IntegrityError

        ws = WorkspaceFactory()
        ScenarioFactory(workspace=ws, slug="same-slug")
        with self.assertRaises(IntegrityError):
            ScenarioFactory(workspace=ws, slug="same-slug")

    def test_different_workspace_same_slug_allowed(self) -> None:
        """Same slug in different workspaces should be allowed."""
        ws1 = WorkspaceFactory()
        ws2 = WorkspaceFactory()
        ScenarioFactory(workspace=ws1, slug="same-slug")
        # This should not raise
        ScenarioFactory(workspace=ws2, slug="same-slug")

    def test_created_at_is_auto_set(self) -> None:
        """created_at should be set automatically on creation."""
        now = timezone.now()
        s = ScenarioFactory()
        self.assertIsNotNone(s.created_at)
        self.assertLess(
            s.created_at - now,
            timedelta(seconds=5),
        )

    def test_updated_at_is_auto_set(self) -> None:
        """updated_at should be set automatically on creation."""
        s = ScenarioFactory()
        self.assertIsNotNone(s.updated_at)

    def test_ordering_by_created_at_descending(self) -> None:
        """Scenarios should be ordered by -created_at (newest first)."""
        ws = WorkspaceFactory()
        s1 = ScenarioFactory(workspace=ws)
        s2 = ScenarioFactory(workspace=ws)
        s3 = ScenarioFactory(workspace=ws)

        qs = Scenario.objects.filter(
            pk__in=[s1.pk, s2.pk, s3.pk],
        )
        pks = list(qs.values_list("pk", flat=True))
        self.assertEqual(pks, sorted(pks, reverse=True))

    def test_description_defaults_to_blank(self) -> None:
        """description should default to empty string."""
        s = ScenarioFactory()
        self.assertEqual(s.description, "")

    def test_description_can_be_set(self) -> None:
        """description should accept a custom value."""
        s = ScenarioFactory(description="A test scenario for urban planning analysis.")
        self.assertEqual(s.description, "A test scenario for urban planning analysis.")

    def test_horizon_year_greater_than_base_year(self) -> None:
        """horizon_year should typically be greater than base_year."""
        s = ScenarioFactory(base_year=2020, horizon_year=2050)
        self.assertGreater(s.horizon_year, s.base_year)
