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
        response = self.client.post(
            url,
            {
                "symbology_type": "single",
                "attribute_column": "",
                "default_color": "#ff0000",
                "default_opacity": "0.8",
                "num_classes": "5",
                "classification_method": "quantile",
                "null_handling": "gray",
            },
        )
        # Should redirect to map
        self.assertIn(response.status_code, [302, 200])
        config = SymbologyConfig.objects.get(layer=self.layer)
        self.assertEqual(config.default_color, "#ff0000")
        self.assertEqual(config.default_opacity, 0.8)

    def test_save_saves_zoom_fields(self) -> None:
        """POST with min_zoom/max_zoom saves them to config."""
        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        self.client.post(
            url,
            {
                "symbology_type": "single",
                "default_color": "#ff0000",
                "default_opacity": "0.8",
                "min_zoom": "5.0",
                "max_zoom": "18.0",
                "null_handling": "gray",
            },
        )
        config = SymbologyConfig.objects.get(layer=self.layer)
        self.assertEqual(config.min_zoom, 5.0)
        self.assertEqual(config.max_zoom, 18.0)
        self.assertEqual(config.default_color, "#ff0000")

    def test_zoom_defaults_when_omitted(self) -> None:
        """POST without zoom fields uses defaults (0.0, 22.0)."""
        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        self.client.post(
            url,
            {
                "symbology_type": "single",
                "default_color": "#00ff00",
                "default_opacity": "0.7",
                "null_handling": "gray",
            },
        )
        config = SymbologyConfig.objects.get(layer=self.layer)
        self.assertEqual(config.min_zoom, 0.0)
        self.assertEqual(config.max_zoom, 22.0)

    def test_preview_includes_zoom(self) -> None:
        """Preview JSON should include minzoom/maxzoom in layout when set."""
        SymbologyConfig.objects.create(
            layer=self.layer,
            symbology_type="single",
            default_color="#0000ff",
            min_zoom=8.0,
            max_zoom=16.0,
        )
        url = reverse("workspace:symbology_preview", args=[self.layer.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["layout"]["minzoom"], 8.0)
        self.assertEqual(data["layout"]["maxzoom"], 16.0)

    def test_auto_generate_endpoint(self) -> None:
        """POST to auto-generate should redirect."""
        url = reverse("workspace:symbology_auto", args=[self.layer.pk])
        response = self.client.post(
            url,
            {
                "attribute_column": "test_col",
            },
        )
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

    def test_editor_includes_gradient_preview(self) -> None:
        """Editor template includes gradient color preview bar when classes exist."""
        config = SymbologyConfig.objects.create(
            layer=self.layer,
            symbology_type="graduated",
            attribute_column="test_col",
        )
        from brewgis.workspace.models import StyleClass

        StyleClass.objects.create(
            symbology=config, label="Low", color="#00ff00", sort_order=0
        )
        StyleClass.objects.create(
            symbology=config, label="High", color="#ff0000", sort_order=1
        )

        url = reverse("workspace:symbology_edit", args=[self.layer.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Color Preview", content)
        self.assertIn("flex-fill", content)
        self.assertIn("#00ff00", content)
        self.assertIn("#ff0000", content)
