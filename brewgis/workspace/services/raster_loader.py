"""Service for loading raster data into PostGIS.

Uses PostGIS raster functions (ST_FromGDALRaster, ST_Tile) to load
GeoTIFF files directly into PostGIS raster tables. No external tools
(raster2pgsql, GDAL) required on the host.
"""

from __future__ import annotations

import logging
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
    """Load a GeoTIFF into a PostGIS raster table.

    Uses ST_FromGDALRaster() to create the raster from the GeoTIFF
    bytes, applies tiling via ST_Tile(), and registers constraints
    via AddRasterConstraints().

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
    assert path.exists(), f"GeoTIFF not found: {geotiff_path}"

    data = path.read_bytes()
    ensure_postgis_raster()

    tile_w, tile_h = tile_size

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {schema}.{table_name} CASCADE"))

        conn.execute(
            text(
                f"CREATE TABLE {schema}.{table_name} AS "  # noqa: S608
                f"SELECT "
                f"  row_number() OVER () AS rid, "
                f"  rast "
                f"FROM ("
                f"  SELECT ST_Tile("
                f"    ST_SetSRID(ST_FromGDALRaster(:data, 'GTiff'), :srid), "
                f"    :tile_w, :tile_h"
                f"  ) AS rast"
                f") tiles"
            ),
            {"data": data, "srid": srid, "tile_w": tile_w, "tile_h": tile_h},
        )

        conn.execute(
            text(
                "SELECT AddRasterConstraints("
                "  :schema::name, :table_name::name, 'rast'::name, "
                "  VARIADIC ARRAY["
                "    'blocksize_x', 'blocksize_y', 'extent', 'srid', "
                "    'numbands', 'pixel_types', 'nodata_values', "
                "    'out_db', 'regular_blocking'"
                "  ]"
                ")"
            ),
            {"schema": schema, "table_name": table_name},
        )

        result = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table_name}"))
        row_count = result.scalar()

    logger.info(
        "Loaded raster %s into %s.%s (%d tiles, SRID %d)",
        geotiff_path,
        schema,
        table_name,
        row_count,
        srid,
    )
    return {
        "success": True,
        "table": f"{schema}.{table_name}",
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
