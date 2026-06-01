"""Tests for the PostGIS raster loading service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

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

    def test_uses_correct_commands(self, tmp_path: Path) -> None:
        """Should invoke raster2pgsql piped to psql with correct args."""
        geotiff = tmp_path / "test.tif"
        geotiff.write_bytes(b"mock geotiff data")

        # Mock subprocess.Popen to simulate success
        mock_raster_proc = MagicMock()
        mock_raster_proc.returncode = 0
        mock_psql_proc = MagicMock()
        mock_psql_proc.returncode = 0

        mock_engine = MagicMock()
        mock_conn = mock_engine.begin.return_value.__enter__.return_value
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_conn.execute.return_value = mock_result

        popen_calls = []

        def fake_popen(cmd, **kwargs):
            popen_calls.append(cmd)
            if "raster2pgsql" in str(cmd):
                return mock_raster_proc
            return mock_psql_proc

        with (
            patch(
                "brewgis.workspace.services.raster_loader.subprocess.Popen",
                side_effect=fake_popen,
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

        # Verify raster2pgsql args
        raster_call = popen_calls[0]
        assert "raster2pgsql" in str(raster_call[0])
        assert "-s" in raster_call and "5070" in raster_call
        assert "-t" in raster_call and "256x256" in raster_call
        assert "-I" in raster_call and "-C" in raster_call and "-d" in raster_call
        assert "test_schema.test_table" in raster_call
        assert "-M" not in raster_call  # should NOT include VACUUM

        # Verify psql args
        psql_call = popen_calls[1]
        assert psql_call[0] == "psql"

    def test_raises_on_missing_raster2pgsql(self, tmp_path: Path) -> None:
        """Should let FileNotFoundError propagate if raster2pgsql missing."""
        geotiff = tmp_path / "test.tif"
        geotiff.write_bytes(b"mock data")

        with (
            patch(
                "brewgis.workspace.services.raster_loader.subprocess.Popen",
                side_effect=FileNotFoundError(
                    "No such file or directory: 'raster2pgsql'"
                ),
            ),
            patch(
                "brewgis.workspace.services.raster_loader.ensure_postgis_raster",
            ),
            pytest.raises(RuntimeError, match="Required tool not found"),
        ):
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
