"""Parcel chip extraction from aerial imagery rasters.

Crops NAIP GeoTIFF chips for each parcel geometry, resizes to ResNet-34
input size (224x224), and applies ImageNet normalization.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import numpy as np
import rasterio
from PIL import Image
from rasterio import windows
from rasterio.errors import RasterioIOError

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)

_RESNET_INPUT_SIZE = 224
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


def extract_chips(  # noqa: C901, PLR0915
    raster_path: str | Path,
    parcels: gpd.GeoDataFrame,
    *,
    parcel_id_col: str = "parcel_id",
) -> Iterator[tuple[str, np.ndarray]]:
    """Extract normalized image chips from a raster for each parcel geometry.

    For each parcel:
      1. Computes the raster window from the parcel geometry bounds.
      2. Reads the 4-band RGBN window, keeps RGB (first 3 bands).
      3. Resizes to (3, 224, 224).
      4. Applies ImageNet normalization: ``(pixel/255.0 - mean) / std``.
      5. Yields ``(parcel_id, chip_float32)``.

    Edge parcels whose window extends beyond raster bounds are zero-padded.
    Parcels wholly outside the raster are skipped.

    Args:
        raster_path: Path to a GeoTIFF raster (e.g. NAIP).
        parcels: GeoDataFrame with parcel geometries and a parcel ID column.
        parcel_id_col: Column name for the parcel identifier.

    Yields:
        ``(parcel_id, chip)`` tuples where *chip* is float32 with shape
        ``(3, 224, 224)``.
    """
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        parcel_crs = parcels.crs
        need_reproject = (
            parcel_crs is not None
            and raster_crs is not None
            and parcel_crs != raster_crs
        )
        if need_reproject:
            from pyproj import Transformer

            _transformer = Transformer.from_crs(parcel_crs, raster_crs, always_xy=True)
        else:
            _transformer = None

        for _, row in parcels.iterrows():
            parcel_id = row[parcel_id_col]
            geometry = row.geometry

            if geometry is None or geometry.is_empty:
                logger.debug("Skipping parcel %s: no geometry", parcel_id)
                continue

            try:
                # Get bounds in raster CRS
                bounds = geometry.bounds  # (minx, miny, maxx, maxy)
                if need_reproject and _transformer is not None:
                    west, south, east, north = bounds
                    x_min, y_min = _transformer.transform(west, south)
                    x_max, y_max = _transformer.transform(east, north)
                    bounds = (x_min, y_min, x_max, y_max)
                # Compute window manually via inverse transform instead of
                # windows.from_bounds to avoid WindowError when reprojected
                # bounds have floating-point rounding at raster edges.
                # from_bounds(left, bottom, right, top) expects top for row_off
                # and bottom for height, so we need (x_min, y_max) → top-left
                # and (x_max, y_min) → bottom-right pixel coords.
                inv = ~src.transform
                left, bottom, right, top = bounds
                col_off, row_off = inv * (left, top)
                col_end, row_end = inv * (right, bottom)
                window = windows.Window(
                    col_off, row_off, col_end - col_off, row_end - row_off
                )
            except (ValueError, KeyError):
                logger.debug("Skipping parcel %s: window computation failed", parcel_id)
                continue

            # Check if window is entirely outside the raster
            if (
                window.col_off >= src.width
                or window.row_off >= src.height
                or window.col_off + window.width <= 0
                or window.row_off + window.height <= 0
            ):
                logger.debug("Skipping parcel %s: outside raster extent", parcel_id)
                continue

            # Clip window to raster bounds for partial-edge parcels
            col_start = max(0, int(window.col_off))
            row_start = max(0, int(window.row_off))
            col_end = min(src.width, int(window.col_off + window.width))
            row_end = min(src.height, int(window.row_off + window.height))
            win_width = col_end - col_start
            win_height = row_end - row_start

            if win_width <= 0 or win_height <= 0:
                logger.debug("Skipping parcel %s: zero-area window", parcel_id)
                continue

            try:
                # Read only RGB bands (first 3 of 4)
                chip_window = windows.Window(
                    col_start, row_start, win_width, win_height
                )
                raw_chip = src.read([1, 2, 3], window=chip_window)
                # raw_chip shape: (3, win_height, win_width)
            except (ValueError, KeyError, RasterioIOError):
                logger.debug("Skipping parcel %s: read failed", parcel_id)
                continue

            # Resize to ResNet input size
            if (
                raw_chip.shape[1] != _RESNET_INPUT_SIZE
                or raw_chip.shape[2] != _RESNET_INPUT_SIZE
            ):
                # PIL expects (H, W, C), int8
                chip_hwc = np.transpose(raw_chip, (1, 2, 0)).astype(np.uint8)
                pil_img = Image.fromarray(chip_hwc, mode="RGB")
                pil_img = pil_img.resize(
                    (_RESNET_INPUT_SIZE, _RESNET_INPUT_SIZE),
                    Image.Resampling.BILINEAR,
                )
                chip = np.array(pil_img, dtype=np.float32).transpose(2, 0, 1)
            else:
                chip = raw_chip.astype(np.float32)

            # Apply ImageNet normalization: pixel/255 - mean, divided by std
            chip = chip / 255.0
            for c in range(3):
                chip[c] = (chip[c] - _IMAGENET_MEAN[c]) / _IMAGENET_STD[c]

            yield (str(parcel_id), chip.astype(np.float32))
