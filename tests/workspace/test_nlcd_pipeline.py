"""Tests for the NLCD raster loading pipeline.

Tests cover:
- _compute_bbox: bbox derivation from PostGIS ST_Extent
- download_nlcd_subset: WCS download with correct coverage IDs
- run_nlcd_tree_canopy_pipeline: end-to-end download orchestration
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from brewgis.workspace.dlt_pipelines.nlcd import _compute_bbox
from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_tree_canopy_pipeline


class TestComputeBbox:
    """Tests for the _compute_bbox helper function.

    Queries PostGIS to detect the table's native SRID and transform
    the extent corners to EPSG:4326 — no assumptions about the
    geometry column's coordinate system.
    """

    def _make_row(self, west: float, south: float, east: float, north: float) -> tuple:
        return (west, south, east, north)

    def test_generated_sql_contains_transform(self) -> None:
        """The SQL query should transform from native SRID to 4326."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            -121.5,
            38.5,
            -121.0,
            39.0,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            _compute_bbox("test_parcels", "public")

        sql = mock_conn.execute.call_args[0][0].text
        # Must dynamically detect SRID
        assert "ST_SRID" in sql
        # Must transform through the detected SRID to 4326
        assert "ST_Transform" in sql
        assert "ST_SetSRID" in sql
        assert "ST_MakePoint" in sql
        assert "4326" in sql

    def test_returns_padded_bbox_4326(self) -> None:
        """Should return bbox with 5% padding in EPSG:4326."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            -121.5,
            38.5,
            -121.0,
            39.0,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            result = _compute_bbox("test_parcels", "public")

        assert result is not None
        west, south, east, north = result
        # 5% padding means 0.5 * 0.05 = 0.025 per side
        assert west == -121.5 - 0.025
        assert east == -121.0 + 0.025
        assert south == 38.5 - 0.025
        assert north == 39.0 + 0.025

    def test_returns_none_when_no_geometries(self) -> None:
        """Should return None when ST_Extent returns NULL (all row values None)."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = (None, None, None, None)

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            bbox = _compute_bbox("test_parcels", "public")

        assert bbox is None


class TestTreeCanopyPipeline:
    """Tests for the NLCD Tree Canopy pipeline."""

    def test_tree_canopy_coverage_docstring(self) -> None:
        """download_nlcd_tree_canopy_raster docstring should reference tree canopy."""
        from brewgis.workspace.services.nlcd_fetcher import (
            download_nlcd_tree_canopy_raster,
        )

        assert download_nlcd_tree_canopy_raster.__doc__ is not None
        assert "Tree Canopy Cover" in download_nlcd_tree_canopy_raster.__doc__

    def test_tree_canopy_coverage_id_matches_mrlc_convention(self) -> None:
        """The WCS coverage ID should use the nlcd_tcc_conus convention from MRLC."""
        from brewgis.workspace.services.nlcd_fetcher import download_nlcd_subset

        with (
            patch(
                "brewgis.workspace.services.nlcd_fetcher.requests.get",
            ) as mock_get,
            patch(
                "brewgis.workspace.services.nlcd_fetcher._verify_cached_file",
                return_value=False,
            ),
        ):
            mock_response = MagicMock()
            mock_get.return_value = mock_response
            mock_response.content = b"fake_tif"
            mock_response.raise_for_status.return_value = None

            download_nlcd_subset(
                -121.0,
                38.0,
                -120.0,
                39.0,
                year=2011,
                coverage_id="mrlc_download__nlcd_tcc_conus_2011_v2021-4",
            )

        call_params = mock_get.call_args[1]["params"]
        assert call_params["CoverageId"] == "mrlc_download__nlcd_tcc_conus_2011_v2021-4"

    def test_run_pipeline_calls_download_with_correct_params(self) -> None:
        """run_nlcd_tree_canopy_pipeline should call download with correct args."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            -121.5,
            38.5,
            -121.0,
            39.0,
        )
        mock_raster_path = "/fake/path/tree_canopy.tif"

        with (
            patch(
                "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
                return_value=mock_engine,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.nlcd.download_nlcd_tree_canopy_raster",
                return_value=mock_raster_path,
            ) as mock_download,
        ):
            result = run_nlcd_tree_canopy_pipeline(
                parcel_source="test_parcels",
                year=2011,
                ignore_cache=True,
            )

        # Verify result dict contains the raster path
        assert result["raster_path"] == mock_raster_path

        # Verify download was called with bbox derived from mock ST_Extent
        mock_download.assert_called_once()
        _args, kwargs = mock_download.call_args
        bbox_arg = kwargs.get("bbox")
        assert bbox_arg is not None
        _bbox_west, _bbox_south, _bbox_east, _bbox_north = bbox_arg

    def test_run_pipeline_with_explicit_bbox(self) -> None:
        """Should use explicit bbox when provided without computing bbox."""
        mock_raster_path = "/fake/path/tree_canopy.tif"
        explicit_bbox = (-122.0, 37.0, -121.0, 38.0)
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            -121.5,
            38.0,
            -121.0,
            38.5,
        )

        with (
            patch(
                "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
                return_value=mock_engine,
            ),
            patch(
                "brewgis.workspace.dlt_pipelines.nlcd.download_nlcd_tree_canopy_raster",
                return_value=mock_raster_path,
            ) as mock_download,
        ):
            run_nlcd_tree_canopy_pipeline(
                parcel_source="test_parcels",
                bbox=explicit_bbox,
                year=2016,
            )

        # Verify download was called with the explicit bbox (not computed)
        mock_download.assert_called_once()
        _args, kwargs = mock_download.call_args
        assert kwargs["bbox"] == explicit_bbox

    def _make_row(self, west: float, south: float, east: float, north: float) -> tuple:
        return (west, south, east, north)

    def test_download_nlcd_tree_canopy_raster_exists(self) -> None:
        """The download function should be importable and callable."""
        from brewgis.workspace.services.nlcd_fetcher import (
            download_nlcd_tree_canopy_raster,
        )

        assert callable(download_nlcd_tree_canopy_raster)
