"""dlt pipeline for raster data extraction (GeoTIFF/COG to PostGIS).

Reads raster metadata and band statistics from GeoTIFF or Cloud
Optimized GeoTIFF (COG) files and loads them into PostgreSQL staging
tables via dlt. Uses rasterio for file I/O (imported lazily so that
module-level import does not fail when rasterio is not installed).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import dlt

from brewgis.soda import validate_nlcd
if TYPE_CHECKING:
    import rasterio

__all__ = [
    "raster_band_source",
    "raster_metadata_source",
    "run_raster_pipeline",
]


def _open_raster(path: str) -> Any:
    """Lazy-import rasterio and open the file."""
    import rasterio  # noqa: PLC0415 — imported lazily to avoid hard dependency

    return rasterio.open(path)


def _read_raster(path: str, band: int) -> tuple:
    """Lazy-import rasterio and read a band array."""
    import rasterio  # noqa: PLC0415

    with rasterio.open(path) as src:
        data = src.read(band)
        return (data, src.nodata, src.units, src.descriptions)


@dlt.source(name="raster_ingest", max_table_nesting=0)
def raster_metadata_source(file_path: str) -> list[Any]:
    """dlt source for raster metadata extraction.

    Args:
        file_path: Path to a GeoTIFF or COG file.

    Returns:
        List with a single :class:`dlt.Resource` yielding the raster
        metadata record.
    """
    return [raster_metadata_resource(file_path)]


@dlt.resource(
    name="raster_metadata",
    write_disposition="replace",
    columns={
        "file_name": {"data_type": "text", "nullable": False},
        "width": {"data_type": "bigint", "nullable": False},
        "height": {"data_type": "bigint", "nullable": False},
        "count": {"data_type": "bigint", "nullable": False},
        "crs": {"data_type": "text", "nullable": True},
        "bounds": {"data_type": "text", "nullable": True},
        "res_x": {"data_type": "double", "nullable": True},
        "res_y": {"data_type": "double", "nullable": True},
        "dtype": {"data_type": "text", "nullable": True},
        "driver": {"data_type": "text", "nullable": True},
    },
)
def raster_metadata_resource(file_path: str) -> Any:
    """Read GeoTIFF metadata and yield a single record."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Raster file not found: {file_path}")

    src = _open_raster(str(path))
    try:
        bounds = src.bounds
        yield {
            "file_name": path.name,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "crs": str(src.crs) if src.crs else None,
            "bounds": f"{bounds.left},{bounds.bottom},{bounds.right},{bounds.top}",
            "res_x": src.res[0],
            "res_y": src.res[1],
            "dtype": src.dtypes[0] if src.dtypes else None,
            "driver": src.driver,
        }
    finally:
        src.close()


@dlt.source(name="raster_bands", max_table_nesting=0)
def raster_band_source(file_path: str) -> list[Any]:
    """dlt source for raster band statistics extraction.

    Args:
        file_path: Path to a GeoTIFF or COG file.

    Returns:
        List with a single :class:`dlt.Resource` yielding per-band
        statistics records.
    """
    return [raster_band_resource(file_path)]


@dlt.resource(
    name="raster_bands",
    write_disposition="replace",
    columns={
        "file_name": {"data_type": "text", "nullable": False},
        "band": {"data_type": "bigint", "nullable": False},
        "min": {"data_type": "double", "nullable": True},
        "max": {"data_type": "double", "nullable": True},
        "mean": {"data_type": "double", "nullable": True},
        "stddev": {"data_type": "double", "nullable": True},
        "nodata": {"data_type": "double", "nullable": True},
        "unit": {"data_type": "text", "nullable": True},
        "description": {"data_type": "text", "nullable": True},
    },
)
def raster_band_resource(file_path: str) -> Any:
    """Read per-band statistics from a GeoTIFF and yield one record per band."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Raster file not found: {file_path}")

    with _open_raster(str(path)) as src:
        for band_idx in range(1, src.count + 1):
            band_data = src.read(band_idx)
            nodata = src.nodata if src.nodata is not None else -9999
            masked = band_data[band_data != nodata]
            yield {
                "file_name": path.name,
                "band": band_idx,
                "min": float(masked.min()) if len(masked) > 0 else None,
                "max": float(masked.max()) if len(masked) > 0 else None,
                "mean": float(masked.mean()) if len(masked) > 0 else None,
                "stddev": float(masked.std()) if len(masked) > 0 else None,
                "nodata": float(nodata),
                "unit": src.units[band_idx - 1] if src.units else None,
                "description": src.descriptions[band_idx - 1] if src.descriptions else None,
            }


def run_raster_pipeline(
    file_path: str,
    schema: str = "public",
) -> dict:
    """Run dlt pipeline to extract raster metadata + bands to staging.

    Args:
        file_path: Path to GeoTIFF/COG file.
        schema: PostgreSQL schema name (default 'public').

    Returns:
        dict with success, metadata_table, bands_table, row_count, load_info.
    """
    pipeline = dlt.pipeline(
        pipeline_name=f"raster_{Path(file_path).stem}",
        destination="postgres",
        dataset_name=schema,
    )

    load_info = pipeline.run(
        [
            raster_metadata_source(file_path),
            raster_band_source(file_path),
        ],
    )

    row_count = 0
    for step in pipeline.last_trace.steps:
        si = step.step_info
        if hasattr(si, "row_counts") and si.row_counts:
            row_count = si.row_counts.get("raster_metadata", 0)
            break

    # Run Soda Core validation on the metadata table
    validation = validate_nlcd(schema=schema, table="raster_metadata")
    if validation["success"]:
        logger.info("Validation passed for %s.raster_metadata", schema)
    else:
        for failure in validation["failures"]:
            logger.warning("Validation failure for %s.raster_metadata: %s", schema, failure)

    return {
        "success": True,
        "metadata_table": f"{schema}.raster_metadata",
        "bands_table": f"{schema}.raster_bands",
        "row_count": row_count,
        "load_info": str(load_info),
        "validation": validation,
    }
