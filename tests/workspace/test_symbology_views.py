"""Integration tests for the symbology editor views."""

from __future__ import annotations

import pytest

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace


@pytest.mark.views
class TestSymbologyViews(TestCase):
    def setUp(self) -> None:
        self.workspace = Workspace.objects.create(
            name="View Test",
            db_schema="public",
        )
        self.layer = Layer.objects.create(
            key="view-layer",
            name="View Layer",
            workspace=self.workspace,
            db_table="view_test_table",
            layer_source="test",
            geometry_type="fill",
        )
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_edit_symbology_get(self) -> None:
        """GET on edit endpoint should return 200."""
        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_symbology_creates_default_config(self) -> None:
        """GET should auto-create a SymbologyConfig if none exists."""
        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        self.client.get(url)
        self.assertTrue(
            SymbologyConfig.objects.filter(layer=self.layer).exists(),
        )

    def test_edit_symbology_post_saves_config(self) -> None:
        """POST should save symbology config and redirect."""
        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        response = self.client.post(url, {
            "symbology_type": "single",
            "attribute_column": "",
            "default_color": "#ff0000",
            "default_opacity": "0.8",
            "num_classes": "5",
            "classification_method": "quantile",
            "null_handling": "gray",
        })
        # Should redirect to map
        self.assertIn(response.status_code, [302, 200])
        config = SymbologyConfig.objects.get(layer=self.layer)
        self.assertEqual(config.default_color, "#ff0000")
        self.assertEqual(config.default_opacity, 0.8)

    def test_auto_generate_endpoint(self) -> None:
        """POST to auto-generate should redirect."""
        url = reverse("workspace:symbology_auto", args=[self.layer.pk])
        response = self.client.post(url, {
            "attribute_column": "test_col",
        })
        self.assertIn(response.status_code, [302, 200])

    def test_preview_endpoint(self) -> None:
        """GET preview should return JSON."""
        url = reverse("workspace:symbology_preview", args=[self.layer.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_preview_with_config(self) -> None:
        """Preview should return paint/layout when config exists."""
        SymbologyConfig.objects.create(
            layer=self.layer,
            symbology_type="single",
            default_color="#00ff00",
        )
        url = reverse("workspace:symbology_preview", args=[self.layer.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("paint", data)
        self.assertIn("fill-color", data["paint"])
