"""Tests for the NLCD raster loading pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

from brewgis.workspace.dlt_pipelines.nlcd import _compute_bbox


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
            -121.5, 38.5, -121.0, 39.0,
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
            -121.5, 38.5, -121.0, 39.0,
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
            None, None, None, None,
        )

        with patch(
            "brewgis.workspace.dlt_pipelines.nlcd.get_engine",
            return_value=mock_engine,
        ):
            bbox = _compute_bbox("empty_table", "public")

        assert bbox is None
