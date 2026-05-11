# ruff: noqa: ANN201
"""Tests for filter views — CRUD, toggle, preview, auth guards."""

from __future__ import annotations

import json

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import Layer, LayerFilter
from tests.factories import LayerFactory, UserFactory, WorkspaceFactory


@pytest.mark.views
class TestLayerFilterList(TestCase):
    """Tests for layer_filter_list view — listing filters per layer."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.url = reverse(
            "workspace:layer_filter_list", kwargs={"layer_pk": self.layer.pk}
        )

    def test_list_requires_auth(self) -> None:
        """Unauthenticated users should be redirected."""
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_list_returns_html(self) -> None:
        """List view should return HTML."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "filter-list-")

    def test_list_shows_filters(self) -> None:
        """List view should show existing filters."""
        LayerFilter.objects.create(layer=self.layer, name="Filter A")
        LayerFilter.objects.create(layer=self.layer, name="Filter B")
        response = self.client.get(self.url)
        self.assertContains(response, "Filter A")
        self.assertContains(response, "Filter B")

    def test_list_shows_empty_state(self) -> None:
        """List view should show empty state when no filters exist."""
        response = self.client.get(self.url)
        self.assertContains(response, "No filters")

    def test_list_404_for_nonexistent_layer(self) -> None:
        """List view should 404 for invalid layer."""
        url = reverse("workspace:layer_filter_list", kwargs={"layer_pk": 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


@pytest.mark.views
class TestLayerFilterCreate(TestCase):
    """Tests for layer_filter_create view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.url = reverse(
            "workspace:layer_filter_create", kwargs={"layer_pk": self.layer.pk}
        )

    def test_create_get_returns_form(self) -> None:
        """GET should return the editor form."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Filter Name")
        self.assertContains(response, "filter_json")

    def test_create_requires_auth(self) -> None:
        """Unauthenticated POST should be redirected."""
        self.client.logout()
        response = self.client.post(self.url, {"name": "Test", "filter_json": "{}"})
        self.assertEqual(response.status_code, 302)

    def test_create_valid(self) -> None:
        """POST with valid data should create a filter."""
        expression = json.dumps(
            {
                "type": "group",
                "operator": "AND",
                "children": [
                    {
                        "type": "column",
                        "field": "existing_du",
                        "operator": "gt",
                        "value": "0",
                        "value_type": "number",
                    }
                ],
            }
        )
        response = self.client.post(
            self.url, {"name": "My Filter", "filter_json": expression}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LayerFilter.objects.count(), 1)
        flt = LayerFilter.objects.first()
        self.assertEqual(flt.name, "My Filter")
        self.assertEqual(flt.layer, self.layer)

    def test_create_empty_name_rejected(self) -> None:
        """POST with empty name should show error."""
        response = self.client.post(self.url, {"name": "", "filter_json": "{}"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "required")
        self.assertEqual(LayerFilter.objects.count(), 0)

    def test_create_invalid_json_rejected(self) -> None:
        """POST with invalid JSON should show error."""
        response = self.client.post(
            self.url, {"name": "Bad", "filter_json": "not valid json"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid filter JSON")
        self.assertEqual(LayerFilter.objects.count(), 0)

    def test_create_404_for_nonexistent_layer(self) -> None:
        """Create should 404 for invalid layer."""
        url = reverse("workspace:layer_filter_create", kwargs={"layer_pk": 99999})
        response = self.client.post(url, {"name": "Test", "filter_json": "{}"})
        self.assertEqual(response.status_code, 404)


@pytest.mark.views
class TestLayerFilterEdit(TestCase):
    """Tests for layer_filter_edit view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.filter = LayerFilter.objects.create(
            layer=self.layer,
            name="Original",
            filter_json={
                "type": "column",
                "field": "x",
                "operator": "eq",
                "value": "1",
            },
        )
        self.url = reverse("workspace:layer_filter_edit", kwargs={"pk": self.filter.pk})

    def test_edit_get_returns_form(self) -> None:
        """GET should return the editor form with existing data."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Original")

    def test_edit_update(self) -> None:
        """POST should update the filter."""
        expression = json.dumps(
            {"type": "column", "field": "y", "operator": "neq", "value": "2"}
        )
        response = self.client.post(
            self.url, {"name": "Updated", "filter_json": expression}
        )
        self.assertEqual(response.status_code, 200)
        self.filter.refresh_from_db()
        self.assertEqual(self.filter.name, "Updated")
        self.assertEqual(self.filter.filter_json["field"], "y")

    def test_edit_404_for_nonexistent(self) -> None:
        """Edit should 404 for invalid pk."""
        url = reverse("workspace:layer_filter_edit", kwargs={"pk": 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


@pytest.mark.views
class TestLayerFilterDelete(TestCase):
    """Tests for layer_filter_delete view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.filter = LayerFilter.objects.create(layer=self.layer, name="To Delete")
        self.url = reverse(
            "workspace:layer_filter_delete", kwargs={"pk": self.filter.pk}
        )

    def test_delete_removes_filter(self) -> None:
        """POST should delete the filter."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LayerFilter.objects.count(), 0)

    def test_delete_requires_post(self) -> None:
        """GET should not delete."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(LayerFilter.objects.count(), 1)

    def test_delete_requires_auth(self) -> None:
        """Unauthenticated POST should be redirected."""
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)

    def test_delete_404_for_nonexistent(self) -> None:
        """Delete should 404 for invalid pk."""
        url = reverse("workspace:layer_filter_delete", kwargs={"pk": 99999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


@pytest.mark.views
class TestLayerFilterToggle(TestCase):
    """Tests for layer_filter_toggle view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.filter = LayerFilter.objects.create(
            layer=self.layer, name="Toggle Me", is_active=False
        )
        self.url = reverse(
            "workspace:layer_filter_toggle", kwargs={"pk": self.filter.pk}
        )

    def test_toggle_active(self) -> None:
        """POST should toggle is_active from False to True."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.filter.refresh_from_db()
        self.assertTrue(self.filter.is_active)

    def test_toggle_inactive(self) -> None:
        """POST should toggle is_active from True to False."""
        self.filter.is_active = True
        self.filter.save()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.filter.refresh_from_db()
        self.assertFalse(self.filter.is_active)

    def test_toggle_requires_post(self) -> None:
        """GET should not toggle."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.filter.refresh_from_db()
        self.assertFalse(self.filter.is_active)

    def test_toggle_requires_auth(self) -> None:
        """Unauthenticated POST should be redirected."""
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)


@pytest.mark.views
class TestLayerFilterPreview(TestCase):
    """Tests for layer_filter_preview view."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.layer = LayerFactory()
        self.filter = LayerFilter.objects.create(
            layer=self.layer,
            name="Preview Me",
            filter_json={
                "type": "column",
                "field": "x",
                "operator": "gt",
                "value": "100",
            },
        )
        self.url = reverse(
            "workspace:layer_filter_preview", kwargs={"pk": self.filter.pk}
        )

    def test_preview_returns_json(self) -> None:
        """GET should return JSON with filter details."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], self.filter.pk)
        self.assertEqual(data["name"], "Preview Me")
        self.assertEqual(data["is_active"], False)
        self.assertIn("filter_json", data)
        self.assertIn("expression", data)

    def test_preview_expression_human_readable(self) -> None:
        """Preview JSON should include a human-readable expression."""
        response = self.client.get(self.url)
        data = response.json()
        self.assertIn("x", data["expression"])

    def test_preview_requires_auth(self) -> None:
        """Unauthenticated GET should be redirected."""
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_preview_404_for_nonexistent(self) -> None:
        """Preview should 404 for invalid pk."""
        url = reverse("workspace:layer_filter_preview", kwargs={"pk": 99999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
