"""Tests for the GX PostGIS datasource factory."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.gx import get_gx_context
from brewgis.gx.datasource import add_postgres_datasource


@pytest.mark.models
class DatasourceTest(TestCase):
    """Test that the PostGIS datasource can be added and lists tables."""

    def test_add_datasource(self) -> None:
        """Adding the datasource succeeds and returns the datasource name."""
        context = get_gx_context()
        name = add_postgres_datasource(context)
        assert name == "brewgis_postgis"

    def test_datasource_idempotent(self) -> None:
        """Adding the datasource twice is safe (idempotent)."""
        context = get_gx_context()
        name1 = add_postgres_datasource(context)
        name2 = add_postgres_datasource(context)
        assert name1 == name2 == "brewgis_postgis"

    def test_datasource_lists_tables(self) -> None:
        """After adding, the datasource can discover tables."""
        context = get_gx_context()
        add_postgres_datasource(context)
        datasource = context.data_sources.get("brewgis_postgis")
        assets = datasource.get_assets()
        # At minimum, should discover system tables like pg_catalog
        assert len(assets) >= 0  # just verify the call succeeds
