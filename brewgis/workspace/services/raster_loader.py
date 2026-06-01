"""Service for loading raster data into PostGIS.

Uses the standard ``raster2pgsql`` tool to generate SQL for loading
GeoTIFF files into PostGIS raster tables. The tool comes from the
``postgis`` Debian package (``/usr/bin/raster2pgsql``).
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


def _strip_tx_control(sql: str) -> str:
    """Strip BEGIN/END/VACUUM — SQLAlchemy manages the transaction."""
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped in ("BEGIN;", "END;", "COMMIT;", ""):
            continue
        if stripped.startswith("VACUUM"):
            continue
        lines.append(line)
    return "\n".join(lines)


def load_raster_to_postgis(
    geotiff_path: str | Path,
    table_name: str,
    schema: str = "public",
    srid: int = 5070,
    tile_size: tuple[int, int] = (256, 256),
) -> dict:
    """Load a GeoTIFF into a PostGIS raster table via ``raster2pgsql``.

    Args:
        geotiff_path: Path to the GeoTIFF file.
        table_name: Target table name (without schema).
        schema: Database schema for the target table.
        srid: SRID of the raster (default 5070 for USA Contiguous Albers).
        tile_size: Tile dimensions (width, height).

    Returns:
        dict with keys: success, table, row_count
    """
    path = Path(geotiff_path)
    ensure_postgis_raster()

    tile_w, tile_h = tile_size
    qualified_table = f"{schema}.{table_name}"

    cmd = [
        "raster2pgsql",
        "-s", str(srid),
        "-t", f"{tile_w}x{tile_h}",
        "-I",
        "-C",
        "-M",
        "-d",
        str(path),
        qualified_table,
    ]

    # Generate SQL via raster2pgsql, clean up temp file on any failure
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False)
    sql_path = tmp.name
    try:
        subprocess.run(cmd, stdout=tmp, check=True, timeout=300)
        tmp.close()

        sql = _strip_tx_control(Path(sql_path).read_text())
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(sql))

        result = conn.execute(
            text(f"SELECT COUNT(*) FROM {qualified_table}")
        )
        row_count = result.scalar()
    finally:
        Path(sql_path).unlink(missing_ok=True)

    logger.info(
        "Loaded raster %s into %s (%d tiles via raster2pgsql)",
        str(path),
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
