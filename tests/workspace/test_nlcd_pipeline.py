"""Tests for the NLCD raster loading pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from brewgis.workspace.dlt_pipelines.nlcd import _compute_bbox


class TestComputeBbox:
    """Tests for the _compute_bbox helper function.

    Uses PostGIS native accessor functions (ST_XMin, ST_YMin, ST_XMax,
    ST_YMax) on ST_Extent — no string parsing.
    """

    def _make_row(self, west: float, south: float, east: float, north: float) -> tuple:
        return (west, south, east, north)

    def test_returns_padded_bbox(self) -> None:
        """Should return bbox with 5% padding on each side."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            600000.0,
            4000000.0,
            700000.0,
            4100000.0,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            bbox = _compute_bbox("test_parcels", "public")

        assert bbox is not None
        west, south, east, north = bbox
        # size 100000 x 100000, 5% = 5000 each side
        assert west == 600000.0 - 5000.0
        assert south == 4000000.0 - 5000.0
        assert east == 700000.0 + 5000.0
        assert north == 4100000.0 + 5000.0

    def test_handles_negative_coordinates(self) -> None:
        """Should handle negative coordinates (projected CRS like UTM)."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.one.return_value = self._make_row(
            1670.208,
            -89316.096,
            5678.901,
            12345.678,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            bbox = _compute_bbox("test_parcels", "public")

        assert bbox is not None
        west, south, east, north = bbox
        assert south < 0
        assert west < east
        assert south < north

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
