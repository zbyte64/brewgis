"""Tests for the onboard_geography management command."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager


@pytest.mark.integration
class TestOnboardGeography:
    """Integration tests for the onboard_geography command."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, db) -> None:
        """Ensure clean state before and after each test."""
        BaseCanvasManager.drop_table()
        yield
        BaseCanvasManager.drop_table()

    def test_missing_required_args(self) -> None:
        """Command should error without required arguments."""
        with pytest.raises(CommandError):
            call_command("onboard_geography")

    def test_invalid_parcels_path(self) -> None:
        """Command should error with invalid parcel file path."""
        with pytest.raises(CommandError):
            call_command(
                "onboard_geography",
                name="Test Geography",
                parcels="/nonexistent/file.geojson",
                state_fips="06",
                county_fips="019",
            )

    @patch("brewgis.workspace.services.base_canvas_etl.BaseCanvasETL.run")
    def test_successful_onboarding(self, mock_etl_run) -> None:
        """Successful ETL should produce summary output."""
        mock_etl_run.return_value = {
            "status": "success",
            "rows": 50,
            "elapsed": 2.5,
            "messages": ["  [1/11] ...", "  [2/11] ..."],
        }

        # Write a minimal valid test GeoJSON
        import json
        import os
        import tempfile

        test_geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-119.8, 36.7],
                                [-119.8, 36.8],
                                [-119.7, 36.8],
                                [-119.7, 36.7],
                                [-119.8, 36.7],
                            ]
                        ],
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False
        ) as tmp:
            json.dump(test_geojson, tmp)
            tmp_path = tmp.name

        try:
            call_command(
                "onboard_geography",
                name="Test Geography",
                parcels=tmp_path,
                state_fips="06",
                county_fips="019",
                skip_census=True,
                skip_lehd=True,
                skip_nlcd=True,
                skip_osm=True,
            )
        finally:
            os.unlink(tmp_path)

        assert mock_etl_run.called

    @patch(
        "brewgis.workspace.management.commands.onboard_geography.Command._print_summary"
    )
    @patch("brewgis.workspace.services.base_canvas_etl.BaseCanvasETL.run")
    def test_onboarding_with_synthetic(self, mock_etl_run, mock_summary) -> None:
        """Onboarding should work with synthetic parcels (testing ETL integration)."""
        # Create synthetic GeoJSON
        import json
        import os
        import tempfile

        test_geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-119.8, 36.7],
                                [-119.8, 36.8],
                                [-119.7, 36.8],
                                [-119.7, 36.7],
                                [-119.8, 36.7],
                            ]
                        ],
                    },
                }
            ],
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False
        ) as tmp:
            json.dump(test_geojson, tmp)
            tmp_path = tmp.name

        mock_etl_run.return_value = {
            "status": "success",
            "rows": 50,
            "elapsed": 2.5,
            "messages": ["  [1/11] ..."],
        }

        try:
            call_command(
                "onboard_geography",
                name="Test Geography",
                parcels=tmp_path,
                state_fips="06",
                county_fips="019",
                skip_census=True,
                skip_lehd=True,
                skip_nlcd=True,
                skip_osm=True,
            )
        finally:
            os.unlink(tmp_path)

        assert mock_etl_run.called
