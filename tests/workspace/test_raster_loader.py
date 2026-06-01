"""Tests for the PostGIS raster loading service."""

from __future__ import annotations

import pytest
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

    def test_uses_raster2pgsql_command(self, tmp_path: Path) -> None:
        """Should call raster2pgsql with correct args and execute SQL."""
        geotiff = tmp_path / "test.tif"
        geotiff.write_bytes(b"mock geotiff data")

        def fake_subprocess_run(cmd, stdout, check, timeout) -> None:
            stdout.write("SELECT 1;")

        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn.execute.return_value = mock_result

        with (
            patch(
                "brewgis.workspace.services.raster_loader.subprocess.run",
                side_effect=fake_subprocess_run,
            ),
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

    def test_raises_on_missing_raster2pgsql(self, tmp_path: Path) -> None:
        """Should let FileNotFoundError propagate if raster2pgsql missing."""
        geotiff = tmp_path / "test.tif"
        geotiff.write_bytes(b"mock data")

        with (
            patch(
                "brewgis.workspace.services.raster_loader.subprocess.run",
                side_effect=FileNotFoundError(
                    "No such file or directory: 'raster2pgsql'"
                ),
            ),
            patch(
                "brewgis.workspace.services.raster_loader.ensure_postgis_raster",
            ),
            patch(
                "brewgis.workspace.services.raster_loader.Path.exists",
                return_value=True,
            ),
            patch(
                "brewgis.workspace.services.raster_loader.Path.read_bytes",
            ),
        ):
            with pytest.raises(FileNotFoundError):
                load_raster_to_postgis(str(geotiff), "test_table")


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
