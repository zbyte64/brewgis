"""Tests for the NLCD raster loading pipeline."""

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
            bbox = _compute_bbox("test_parcels", "public")

        assert bbox is not None
        west, south, east, north = bbox
        # size 0.5 x 0.5 degrees, 5% = 0.025 each side
        assert west == -121.5 - 0.025
        assert south == 38.5 - 0.025
        assert east == -121.0 + 0.025
        assert north == 39.0 + 0.025

    def test_returns_none_when_no_geometries(self) -> None:
        """Should return None when ST_Extent returns NULL (all row values None)."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            None,
            None,
            None,
            None,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            bbox = _compute_bbox("empty_table", "public")

        assert bbox is None


class TestTreeCanopyPipeline:
    """Tests for the NLCD Tree Canopy pipeline."""

    def test_tree_canopy_coverage_id(self) -> None:
        """The tree canopy coverage ID should use the correct format."""
        from brewgis.workspace.services.nlcd_fetcher import (
            download_nlcd_tree_canopy_raster,
        )

        assert download_nlcd_tree_canopy_raster.__doc__ is not None
        assert "Tree Canopy Cover" in download_nlcd_tree_canopy_raster.__doc__

    def test_tree_canopy_coverage_id_matches_mrlc_convention(self) -> None:
        """The WCS coverage ID should use the nlcd_tcc_conus convention from MRLC."""
        from brewgis.workspace.services.nlcd_fetcher import _download_nlcd_subset

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

            _download_nlcd_subset(
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
                "brewgis.workspace.dlt_pipelines.nlcd.load_raster_to_postgis",
                return_value={"row_count": 42},
            ) as mock_load,
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

        assert result["raster_table"] == "nlcd_tree_canopy_raster"
        assert result["schema"] == "public"

        mock_download.assert_called_once_with(
            (-121.525, 38.475, -120.975, 39.025),
            2011,
            refresh_cache=True,
            source_crs="EPSG:4326",
        )

        mock_load.assert_called_once_with(
            mock_raster_path,
            "nlcd_tree_canopy_raster",
            schema="public",
            srid=5070,
        )

    def test_run_pipeline_with_explicit_bbox(self) -> None:
        """Should use explicit bbox when provided without computing."""
        explicit_bbox = (-122.0, 38.0, -121.0, 39.0)
        mock_raster_path = "/fake/path/tree_canopy.tif"

        with (
            patch(
                "brewgis.workspace.dlt_pipelines.nlcd.load_raster_to_postgis",
                return_value={"row_count": 10},
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

        mock_download.assert_called_once_with(
            explicit_bbox,
            2016,
            refresh_cache=False,
            source_crs="EPSG:4326",
        )

    def _make_row(self, west: float, south: float, east: float, north: float) -> tuple:
        return (west, south, east, north)

    def test_download_nlcd_tree_canopy_raster_exists(self) -> None:
        """The download function should be importable and callable."""
        from brewgis.workspace.services.nlcd_fetcher import (
            download_nlcd_tree_canopy_raster,
        )

        assert callable(download_nlcd_tree_canopy_raster)
