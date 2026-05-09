# ruff: noqa: ANN201
"""Tests for LayerFilter model — defaults, creation, string representation."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.workspace.models import Layer, LayerFilter
from tests.factories import LayerFactory


@pytest.mark.models
class TestLayerFilterModel(TestCase):
    """Tests for LayerFilter model fields and behavior."""

    def setUp(self) -> None:
        self.layer = LayerFactory()

    def test_create_filter_defaults(self) -> None:
        """A filter should be created with default values."""
        flt = LayerFilter.objects.create(layer=self.layer, name="Test Filter")
        self.assertEqual(flt.name, "Test Filter")
        self.assertEqual(flt.filter_json, {})
        self.assertFalse(flt.is_active)
        self.assertIsNotNone(flt.created_at)
        self.assertIsNotNone(flt.updated_at)
        self.assertEqual(flt.layer, self.layer)

    def test_create_filter_with_json(self) -> None:
        """A filter should store the provided JSON expression tree."""
        expression = {
            "type": "group",
            "operator": "AND",
            "children": [
                {"type": "column", "field": "existing_du", "operator": "gt", "value": "0", "value_type": "number"}
            ],
        }
        flt = LayerFilter.objects.create(layer=self.layer, name="DU > 0", filter_json=expression)
        self.assertEqual(flt.filter_json, expression)
        self.assertEqual(flt.filter_json["type"], "group")
        self.assertEqual(flt.filter_json["operator"], "AND")
        self.assertEqual(len(flt.filter_json["children"]), 1)

    def test_is_active_flag(self) -> None:
        """A filter should be togglable between active and inactive."""
        flt = LayerFilter.objects.create(layer=self.layer, name="Active Filter", is_active=True)
        self.assertTrue(flt.is_active)
        flt.is_active = False
        flt.save()
        self.assertFalse(flt.is_active)

    def test_filter_str_representation(self) -> None:
        """String representation should include filter name and layer name."""
        self.layer.name = "Parcels"
        self.layer.save()
        flt = LayerFilter.objects.create(layer=self.layer, name="High Density")
        expected = f"High Density ({self.layer.name})"
        self.assertEqual(str(flt), expected)

    def test_layer_filter_relation(self) -> None:
        """Layer.filters should return all filters for that layer (related_name)."""
        LayerFilter.objects.create(layer=self.layer, name="Filter A")
        LayerFilter.objects.create(layer=self.layer, name="Filter B")
        self.assertEqual(self.layer.filters.count(), 2)

    def test_multiple_layers_independent_filters(self) -> None:
        """Filters should be scoped per-layer."""
        layer2 = LayerFactory()
        LayerFilter.objects.create(layer=self.layer, name="Layer 1 Filter")
        LayerFilter.objects.create(layer=layer2, name="Layer 2 Filter")
        self.assertEqual(self.layer.filters.count(), 1)
        self.assertEqual(layer2.filters.count(), 1)

    def test_cascade_delete(self) -> None:
        """Deleting a layer should cascade-delete its filters."""
        LayerFilter.objects.create(layer=self.layer, name="To Delete")
        pk = self.layer.pk
        self.layer.delete()
        self.assertEqual(LayerFilter.objects.filter(layer__pk=pk).count(), 0)

    def test_filter_ordering(self) -> None:
        """Filters should be ordered by name by default."""
        LayerFilter.objects.create(layer=self.layer, name="Z Filter")
        LayerFilter.objects.create(layer=self.layer, name="A Filter")
        LayerFilter.objects.create(layer=self.layer, name="M Filter")
        names = [f.name for f in LayerFilter.objects.filter(layer=self.layer)]
        self.assertEqual(names, ["A Filter", "M Filter", "Z Filter"])
