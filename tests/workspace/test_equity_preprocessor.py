"""Tests for Phase 1c: ACS Equity Data Wrapper and Phase 1e: POI Cache."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import TestCase


class TestPOICacheModel(TestCase):
    """Tests for the POICache model."""

    def setUp(self):
        from brewgis.workspace.models import POICache, Workspace

        self.workspace = Workspace.objects.create(name="Test Workspace")
        POICache.objects.create(
            workspace=self.workspace,
            name="food_poi",
            geojson_data={"type": "FeatureCollection", "features": []},
            source="osm",
        )

    def test_poicache_created(self):
        from brewgis.workspace.models import POICache

        cached = POICache.objects.get(
            workspace=self.workspace, name="food_poi"
        )
        assert cached.geojson_data["type"] == "FeatureCollection"
        assert cached.source == "osm"

    def test_poicache_default_source(self):
        from brewgis.workspace.models import POICache

        poicache = POICache(
            workspace=self.workspace,
            name="test_cache",
            geojson_data={"type": "FeatureCollection", "features": []},
        )
        assert poicache.source == "osm"

    def test_poicache_unique_together(self):
        from django.db.utils import IntegrityError

        from brewgis.workspace.models import POICache

        with pytest.raises(IntegrityError):
            POICache.objects.create(
                workspace=self.workspace,
                name="food_poi",
                geojson_data={"type": "FeatureCollection", "features": []},
            )

    def test_poicache_str(self):
        from brewgis.workspace.models import POICache

        poicache = POICache.objects.get(
            workspace=self.workspace, name="food_poi"
        )
        assert "POICache" in str(poicache)
        assert str(self.workspace.pk) in str(poicache)


class TestACSEquityPreprocessor(TestCase):
    """Tests for the ACS equity data wrapper preprocessor."""

    def setUp(self):
        from brewgis.workspace.models import Scenario, Workspace

        self.workspace = Workspace.objects.create(name="Test")
        self.scenario = Scenario.objects.create(
            name="Test",
            slug="test",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )

    @staticmethod
    def _mock_cursor():
        """Build a mock cursor context manager."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (False,)
        mock_cursor.rowcount = 0
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = None
        return mock_cursor

    @patch("django.db.connection.cursor")
    def test_no_acs_table_returns_uniform_defaults(self, mock_cursor_factory):
        """Without acs_equity_table var, returns uniform_defaults."""
        mock_cursor_factory.return_value = self._mock_cursor()
        from brewgis.workspace.analysis.equity.preprocessor import (
            run_acs_equity_preprocessor,
        )

        result = run_acs_equity_preprocessor(
            {
                "target_schema": "public",
                "base_canvas_table": "base_canvas",
            }
        )
        assert result["success"] is True
        assert result["method"] == "uniform_defaults"

    @patch("django.db.connection.cursor")
    def test_nonexistent_acs_table_falls_back(self, mock_cursor_factory):
        """If ACS table is set but doesn't exist, falls back gracefully."""
        mock_cursor_factory.return_value = self._mock_cursor()
        from brewgis.workspace.analysis.equity.preprocessor import (
            run_acs_equity_preprocessor,
        )

        result = run_acs_equity_preprocessor(
            {
                "target_schema": "public",
                "base_canvas_table": "base_canvas",
                "acs_equity_table": "nonexistent_table_12345",
            }
        )
        assert result["success"] is True
        # Should still succeed with fallback method
        assert result["method"] in ("uniform_defaults", "uniform_defaults_fallback")
