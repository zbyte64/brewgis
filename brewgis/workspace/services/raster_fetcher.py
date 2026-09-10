"""Raster (GeoTIFF) metadata and band-statistics extraction.

Reads a GeoTIFF via rasterio and materializes its metadata (footprint,
CRS, dimensions) and per-band statistics into Postgres, so a raster file
already on disk can be registered as a workspace Layer.
"""

from __future__ import annotations

import logging
from typing import Any

import rasterio
from rasterio.warp import transform_bounds

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text

logger = logging.getLogger(__name__)

_METADATA_TABLE = "raster_metadata"
_BANDS_TABLE = "raster_bands"


def _all_band_statistics(
    dataset: rasterio.DatasetReader, band_count: int
) -> list[dict[str, float | None]]:
    """Return min/max/mean/std per band, tolerating all-nodata bands."""
    empty = {
        "min_value": None,
        "max_value": None,
        "mean_value": None,
        "std_value": None,
    }
    try:
        stats = dataset.stats(indexes=list(range(1, band_count + 1)), approx=True)
    except rasterio.errors.StatisticsError:
        logger.warning("No valid data for statistics (all nodata?)")
        return [dict(empty) for _ in range(band_count)]
    return [
        {
            "min_value": s.min,
            "max_value": s.max,
            "mean_value": s.mean,
            "std_value": s.std,
        }
        for s in stats
    ]


def run_raster_pipeline(file_path: str, schema: str) -> dict[str, Any]:
    """Extract metadata and per-band statistics from a GeoTIFF into *schema*.

    Creates (or appends to) ``{schema}.raster_metadata`` — one row per
    imported file, with its footprint reprojected to EPSG:4326 — and
    ``{schema}.raster_bands`` — one row per band, linked back via
    ``metadata_id``.

    Args:
        file_path: Path to a GeoTIFF file readable by GDAL/rasterio.
        schema: Workspace schema to write the metadata/bands tables into.

    Returns:
        Dict with ``metadata_table``, ``bands_table``, and ``row_count``
        (the number of bands extracted).
    """
    with rasterio.open(file_path) as dataset:
        crs = dataset.crs.to_string() if dataset.crs else None
        bounds_4326 = (
            transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds)
            if dataset.crs
            else dataset.bounds
        )
        min_lng, min_lat, max_lng, max_lat = bounds_4326
        width, height = dataset.width, dataset.height
        band_count = dataset.count
        dtype = dataset.dtypes[0] if dataset.dtypes else None
        nodata = dataset.nodata

        band_stats = _all_band_statistics(dataset, band_count)

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(
            text(f"""
                CREATE TABLE IF NOT EXISTS "{schema}"."{_METADATA_TABLE}" (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    crs TEXT,
                    width INTEGER,
                    height INTEGER,
                    band_count INTEGER,
                    dtype TEXT,
                    nodata DOUBLE PRECISION,
                    geometry GEOMETRY(POLYGON, 4326),
                    created_at TIMESTAMPTZ DEFAULT now()
                )
                """)
        )
        conn.execute(
            text(f"""
                CREATE TABLE IF NOT EXISTS "{schema}"."{_BANDS_TABLE}" (
                    id SERIAL PRIMARY KEY,
                    metadata_id INTEGER REFERENCES "{schema}"."{_METADATA_TABLE}"(id)
                        ON DELETE CASCADE,
                    band_index INTEGER,
                    min_value DOUBLE PRECISION,
                    max_value DOUBLE PRECISION,
                    mean_value DOUBLE PRECISION,
                    std_value DOUBLE PRECISION
                )
                """)
        )

        metadata_id = conn.execute(
            text(f"""
                INSERT INTO "{schema}"."{_METADATA_TABLE}"
                    (file_path, crs, width, height, band_count, dtype, nodata, geometry)
                VALUES
                    (:file_path, :crs, :width, :height, :band_count, :dtype, :nodata,
                     ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326))
                RETURNING id
                """),
            {
                "file_path": file_path,
                "crs": crs,
                "width": width,
                "height": height,
                "band_count": band_count,
                "dtype": dtype,
                "nodata": nodata,
                "min_lng": min_lng,
                "min_lat": min_lat,
                "max_lng": max_lng,
                "max_lat": max_lat,
            },
        ).scalar_one()

        for band_index, stats in enumerate(band_stats, start=1):
            conn.execute(
                text(f"""
                    INSERT INTO "{schema}"."{_BANDS_TABLE}"
                        (metadata_id, band_index, min_value, max_value, mean_value, std_value)
                    VALUES
                        (:metadata_id, :band_index, :min_value, :max_value, :mean_value, :std_value)
                    """),
                {"metadata_id": metadata_id, "band_index": band_index, **stats},
            )

    logger.info(
        "Wrote raster metadata (id=%s, %d bands) to %s.%s / %s.%s",
        metadata_id,
        band_count,
        schema,
        _METADATA_TABLE,
        schema,
        _BANDS_TABLE,
    )
    return {
        "metadata_table": _METADATA_TABLE,
        "bands_table": _BANDS_TABLE,
        "row_count": band_count,
    }
