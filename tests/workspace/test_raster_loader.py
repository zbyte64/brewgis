"""Tests for the PostGIS raster loading service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from brewgis.workspace.services.raster_loader import drop_raster_table
from brewgis.workspace.services.raster_loader import ensure_postgis_raster
from brewgis.workspace.services.raster_loader import load_raster_to_postgis


class TestEnsurePostgisRaster:
    """Tests for the postgis_raster extension check."""

    def test_creates_extension_when_missing(self) -> None:
        """Should run CREATE EXTENSION IF NOT EXISTS."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value

        with patch(
            "brewgis.workspace.services.raster_loader.get_engine",
            return_value=mock_engine,
        ):
            ensure_postgis_raster()

        sql = mock_conn.execute.call_args[0][0].text
        assert "CREATE EXTENSION IF NOT EXISTS postgis_raster" in sql


class TestLoadRasterToPostgis:
    """Tests for loading a GeoTIFF into a PostGIS raster table."""

    def test_missing_file_returns_error(self) -> None:
        """Should return error dict for non-existent file."""
        result = load_raster_to_postgis(
            "/nonexistent/file.tif",
            "test_table",
        )
        assert not result["success"]
        assert "not found" in result["error"]

    def test_invalid_path_returns_error(self) -> None:
        """Should return error dict for invalid path (directory)."""
        result = load_raster_to_postgis(
            "/proc/self",  # exists but is not a GeoTIFF
            "test_table",
        )
        assert not result["success"]
        assert "Failed to read GeoTIFF" in result["error"]

    def test_executes_correct_sql_sequence(self, tmp_path: Path) -> None:
        """Should issue DROP TABLE, CREATE TABLE, AddRasterConstraints, COUNT."""
        geotiff = tmp_path / "test.tif"
        geotiff.write_bytes(b"mock geotiff data")

        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn.execute.return_value = mock_result

        with (
            patch(
                "brewgis.workspace.services.raster_loader.get_engine",
                return_value=mock_engine,
            ),
            patch(
                "brewgis.workspace.services.raster_loader.ensure_postgis_raster",
            ),
        ):
            result = load_raster_to_postgis(
                str(geotiff),
                "test_table",
                schema="test_schema",
                srid=5070,
            )

        assert result["success"]
        assert result["table"] == "test_schema.test_table"
        assert result["row_count"] == 42

        # Verify the SQL calls in order
        calls = [str(c[0][0].text) for c in mock_conn.execute.call_args_list]
        assert any("DROP TABLE IF EXISTS test_schema.test_table" in c for c in calls)
        assert any(
            "CREATE TABLE test_schema.test_table AS" in c
            and "ST_FromGDALRaster" in c
            and "ST_Tile" in c
            for c in calls
        )
        assert any("AddRasterConstraints" in c for c in calls)
        assert any("SELECT COUNT(*) FROM test_schema.test_table" in c for c in calls)

    def test_verify_srid_parameter(self, tmp_path: Path) -> None:
        """Should pass SRID to ST_SetSRID."""
        geotiff = tmp_path / "test_4326.tif"
        geotiff.write_bytes(b"mock data")

        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_conn.execute.return_value = mock_result

        with (
            patch(
                "brewgis.workspace.services.raster_loader.get_engine",
                return_value=mock_engine,
            ),
            patch(
                "brewgis.workspace.services.raster_loader.ensure_postgis_raster",
            ),
        ):
            load_raster_to_postgis(
                str(geotiff),
                "test_table",
                srid=4326,
            )

        # Check the CREATE TABLE call had srid parameter
        create_call = None
        for call in mock_conn.execute.call_args_list:
            sql = str(call[0][0].text)
            if "CREATE TABLE" in sql:
                create_call = call
                break
        assert create_call is not None
        params = create_call[0][1]
        assert params["srid"] == 4326
        assert params["data"] == b"mock data"


class TestDropRasterTable:
    """Tests for dropping a raster table."""

    def test_executes_drop_table(self) -> None:
        """Should execute DROP TABLE IF EXISTS ... CASCADE."""
        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value

        with patch(
            "brewgis.workspace.services.raster_loader.get_engine",
            return_value=mock_engine,
        ):
            result = drop_raster_table("test_table", schema="test_schema")

        assert result["success"]
        sql = mock_conn.execute.call_args[0][0].text
        assert "DROP TABLE IF EXISTS test_schema.test_table CASCADE" in sql
