"""Tests for Phase 4a: Public Scenario Gallery.

Covers Scenario.published/public_token model fields, the public read-only
scenario map view, and the scenario_toggle_publish endpoint.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import User
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace


class TestScenarioPublishedModel(TestCase):
    """Tests for Scenario.published and public_token fields."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test")
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    def test_default_not_published(self):
        self.assertFalse(self.scenario.published)

    def test_default_public_token_is_not_null(self):
        self.assertIsNotNone(self.scenario.public_token)
        self.assertIsInstance(self.scenario.public_token, uuid.UUID)

    def test_unique_public_tokens(self):
        other = Scenario.objects.create(
            name="Other",
            slug="other",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )
        self.assertNotEqual(self.scenario.public_token, other.public_token)

    def test_toggle_published_on(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        self.scenario.refresh_from_db()
        self.assertTrue(self.scenario.published)

    def test_toggle_published_off(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        self.scenario.refresh_from_db()
        self.scenario.published = False
        self.scenario.save(update_fields=["published"])
        self.scenario.refresh_from_db()
        self.assertFalse(self.scenario.published)


class TestPublicScenarioMapView(TestCase):
    """Tests for the public read-only map view."""

    def setUp(self):
        self.client = Client()
        self.workspace = Workspace.objects.create(name="Test")
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    def _url(self, scenario: Scenario | None = None) -> str:
        s = scenario or self.scenario
        return reverse("workspace:public_scenario_map", args=[s.public_token])

    def test_published_scenario_returns_200(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_published_scenario_uses_workspace_map_template(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.get(self._url())
        self.assertTemplateUsed(response, "workspace_map.html")

    def test_unpublished_scenario_returns_404(self):
        """Unpublished scenarios should not be revealed (404, not 403)."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_token_returns_404(self):
        bad_token = uuid.uuid4()
        url = reverse("workspace:public_scenario_map", args=[bad_token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_invalid_token_format_returns_404(self):
        """Non-UUID token should raise 404."""
        url = reverse(
            "workspace:public_scenario_map",
            kwargs={"token": uuid.uuid4()},
        )
        # Replace the UUID portion with an invalid string
        bad_url = f"/workspace/public/not-a-uuid/"
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)

    def test_public_view_has_read_only_context(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.get(self._url())
        self.assertIn("is_public_view", response.context)
        self.assertTrue(response.context["is_public_view"])
        self.assertIn("disable_paint", response.context)
        self.assertTrue(response.context["disable_paint"])

    def test_public_view_has_scenario_in_context(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.get(self._url())
        self.assertEqual(response.context["scenario"], self.scenario)

    def test_public_view_has_public_token_in_context(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.get(self._url())
        self.assertEqual(
            response.context["public_token"],
            self.scenario.public_token,
        )


class TestTogglePublishView(TestCase):
    """Tests for the scenario_toggle_publish view."""

    def setUp(self):
        self.client = Client()
        self.workspace = Workspace.objects.create(name="Test")
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )
        self.user = User.objects.create_user(
            username="testuser", password="testpass"
        )
        self.client.login(username="testuser", password="testpass")

    def _url(self) -> str:
        return reverse(
            "workspace:scenario_toggle_publish",
            args=[self.workspace.pk, self.scenario.pk],
        )

    def test_toggle_on(self):
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["published"])
        self.assertIsNotNone(data["public_token"])

    def test_toggle_off(self):
        self.scenario.published = True
        self.scenario.save(update_fields=["published"])
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["published"])

    def test_toggle_on_assigns_token_if_missing(self):
        """Toggling published on should create a token if one doesn't exist."""
        self.scenario.public_token = None
        self.scenario.save(update_fields=["public_token"])
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["published"])
        self.assertIsNotNone(data["public_token"])

    def test_get_returns_405(self):
        """Only POST is allowed."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)

    def test_toggle_requires_auth(self):
        self.client.logout()
        response = self.client.post(self._url())
        # @user_passes_test redirects unauthenticated users to login
        self.assertEqual(response.status_code, 302)

    def test_toggle_wrong_workspace_returns_404(self):
        """Mismatched workspace_pk should 404."""
        wrong_ws = Workspace.objects.create(name="Other")
        url = reverse(
            "workspace:scenario_toggle_publish",
            args=[wrong_ws.pk, self.scenario.pk],
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
