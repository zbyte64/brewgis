"""Tests for the legend view endpoint."""

from __future__ import annotations

import pytest
from django.test import TestCase
from django.urls import reverse

from tests.factories import LayerFactory
from tests.factories import SymbologyConfigFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestLegendViews(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory()
        self.layer = LayerFactory(workspace=self.workspace, name="Test Layer")
        self.config = SymbologyConfigFactory(
            layer=self.layer, symbology_type="single", default_color="#ff0000"
        )

    def test_legend_endpoint_returns_html(self) -> None:
        url = reverse("workspace:layer_legend", kwargs={"layer_pk": self.layer.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response["content-type"] == "text/html; charset=utf-8"
        content = response.content.decode()
        assert "Test Layer" in content
        assert "#ff0000" in content

    def test_legend_endpoint_requires_auth(self) -> None:
        self.client.logout()
        url = reverse("workspace:layer_legend", kwargs={"layer_pk": self.layer.pk})
        response = self.client.get(url)
        assert response.status_code == 302  # redirect to login

    def test_legend_endpoint_404_for_nonexistent_layer(self) -> None:
        url = reverse("workspace:layer_legend", kwargs={"layer_pk": 999999})
        response = self.client.get(url)
        assert response.status_code == 404
