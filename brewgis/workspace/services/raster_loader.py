"""Service for loading raster data into PostGIS.

Uses the standard ``raster2pgsql`` tool to generate SQL for loading
GeoTIFF files into PostGIS raster tables. Requires ``postgresql-XX-postgis-3``
to be installed for the ``raster2pgsql`` binary.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import text

from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)


def ensure_postgis_raster() -> None:
    """Enable the postgis_raster extension if not already enabled."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_raster"))


def load_raster_to_postgis(
    geotiff_path: str | Path,
    table_name: str,
    schema: str = "public",
    srid: int = 5070,
    tile_size: tuple[int, int] = (256, 256),
) -> dict:
    """Load a GeoTIFF into a PostGIS raster table via ``raster2pgsql``.

    The GeoTIFF is converted to a PostGIS raster table using the
    standard ``raster2pgsql`` tool with tiling and raster constraints.
    The generated SQL is then executed via the existing database
    connection.

    Args:
        geotiff_path: Path to the GeoTIFF file.
        table_name: Target table name (without schema).
        schema: Database schema for the target table.
        srid: SRID of the raster (default 5070 for USA Contiguous Albers).
        tile_size: Tile dimensions (width, height).

    Returns:
        dict with keys: success, table, row_count (on success) or
        success, error (on failure).
    """
    path = Path(geotiff_path)
    if not path.exists():
        return {"success": False, "error": f"GeoTIFF not found: {geotiff_path}"}

    ensure_postgis_raster()

    tile_w, tile_h = tile_size
    qualified_table = f"{schema}.{table_name}"

    # Generate SQL via raster2pgsql
    cmd = [
        "raster2pgsql",
        "-s", str(srid),
        "-t", f"{tile_w}x{tile_h}",
        "-I",  # spatial index
        "-C",  # raster constraints
        "-M",  # vacuum analyze
        "-d",  # drop and recreate
        str(path),
        qualified_table,
    ]

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False,
        ) as tmp:
            subprocess.run(cmd, stdout=tmp, check=True, timeout=300)
            sql_path = tmp.name
    except subprocess.CalledProcessError as exc:
        return {
            "success": False,
            "error": f"raster2pgsql failed (exit {exc.returncode}): {exc}",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "raster2pgsql timed out after 300s",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": (
                "raster2pgsql not found. Install postgresql-XX-postgis-3 "
                "(e.g. postgresql-15-postgis-3)."
            ),
        }

    # Execute generated SQL
    try:
        sql = Path(sql_path).read_text()
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:
        Path(sql_path).unlink(missing_ok=True)
        return {"success": False, "error": f"Failed to execute raster SQL: {exc}"}

    Path(sql_path).unlink(missing_ok=True)

    # Count rows
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(f"SELECT COUNT(*) FROM {qualified_table}")
        )
        row_count = result.scalar()

    logger.info(
        "Loaded raster %s into %s (%d tiles via raster2pgsql)",
        str(path),
        qualified_table,
        row_count,
    )
    return {
        "success": True,
        "table": qualified_table,
        "row_count": row_count,
    }


def drop_raster_table(table_name: str, schema: str = "public") -> dict:
    """Drop a raster table from PostGIS.

    Args:
        table_name: Table to drop (without schema).
        schema: Database schema.

    Returns:
        dict with success status.
    """
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{table_name} CASCADE"))
    logger.info("Dropped raster table %s.%s", schema, table_name)
    return {"success": True}
