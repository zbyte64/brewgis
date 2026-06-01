"""Service for loading raster data into PostGIS.

Uses the standard ``raster2pgsql`` tool piped to ``psql`` to load
GeoTIFF files into PostGIS raster tables. Both tools come from the
``postgis`` and ``postgresql-client`` Debian packages.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from sqlalchemy import text
from django.conf import settings

from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)


def _database_url() -> str:
    """Build a PostgreSQL connection URL from Django DATABASES settings."""
    db = settings.DATABASES["default"]
    return (
        f"postgresql://{db['USER']}:{db['PASSWORD']}"
        f"@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    )


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
    """Load a GeoTIFF into a PostGIS raster table via ``raster2pgsql | psql``.

    Args:
        geotiff_path: Path to the GeoTIFF file.
        table_name: Target table name (without schema).
        schema: Database schema for the target table.
        srid: SRID of the raster (default 5070 for USA Contiguous Albers).
        tile_size: Tile dimensions (width, height).

    Returns:
        dict with keys: success, table, row_count
    """
    ensure_postgis_raster()

    tile_w, tile_h = tile_size
    qualified_table = f"{schema}.{table_name}"

    raster2pgsql_args = [
        "raster2pgsql",
        "-s", str(srid),
        "-t", f"{tile_w}x{tile_h}",
        "-I",
        "-C",
        "-d",
        str(Path(geotiff_path)),
        qualified_table,
    ]

    psql_args = ["psql", _database_url()]

    # Pipe raster2pgsql → psql
    try:
        raster_proc = subprocess.Popen(raster2pgsql_args, stdout=subprocess.PIPE)
        psql_proc = subprocess.Popen(psql_args, stdin=raster_proc.stdout)
        raster_proc.stdout.close()
        raster_proc.wait()
        psql_proc.wait()

        if raster_proc.returncode != 0 or psql_proc.returncode != 0:
            raise RuntimeError("raster2pgsql | psql pipeline failed")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required tool not found: {exc.filename}. "
            "Install postgis and postgresql-client packages."
        ) from exc

    # Count rows
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {qualified_table}"))
        row_count = result.scalar()

    logger.info(
        "Loaded raster %s into %s (%d tiles)",
        str(geotiff_path),
        qualified_table,
        row_count,
    )
    return {"success": True, "table": qualified_table, "row_count": row_count}


def drop_raster_table(table_name: str, schema: str = "public") -> dict:
    """Drop a raster table from PostGIS."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{table_name} CASCADE"))
    logger.info("Dropped raster table %s.%s", schema, table_name)
    return {"success": True}
