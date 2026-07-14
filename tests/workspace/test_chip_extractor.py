"""Tests for chip extraction from aerial imagery rasters."""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box

from brewgis.workspace.services.chip_extractor import extract_chips


def _create_synthetic_naip(path: Path, width: int = 224, height: int = 224) -> None:
    """Create a 4-band RGBN synthetic GeoTIFF with known pixel values."""
    # Band 1 (R): gradient, Band 2 (G): solid 128, Band 3 (B): solid 64, Band 4 (NIR): solid 200
    band1 = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
    band2 = np.full((height, width), 128, dtype=np.uint8)
    band3 = np.full((height, width), 64, dtype=np.uint8)
    band4 = np.full((height, width), 200, dtype=np.uint8)
    data = np.stack([band1, band2, band3, band4], axis=0)

    transform = rasterio.transform.from_bounds(
        -121.5, 38.5, -121.3, 38.7, width, height
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=4,
        dtype=np.uint8,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)


class TestExtractChips:
    """Unit tests for the extract_chips function."""

    def test_extract_single_chip_shape(self) -> None:
        """Should yield exactly one chip with expected shape (3, 224, 224)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raster_path = Path(tmpdir) / "test_naip.tif"
            _create_synthetic_naip(raster_path)

            # Create one parcel covering the whole raster
            gdf = gpd.GeoDataFrame(
                {"parcel_id": ["p001"]},
                geometry=[box(-121.5, 38.5, -121.3, 38.7)],
                crs="EPSG:4326",
            )

            chips = list(extract_chips(raster_path, gdf))
            assert len(chips) == 1

            pid, chip = chips[0]
            assert pid == "p001"
            assert chip.shape == (3, 224, 224)
            assert chip.dtype == np.float32

    def test_chip_normalization_range(self) -> None:
        """After normalization, pixel values should be approximately in [-3, 3]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raster_path = Path(tmpdir) / "test_naip.tif"
            _create_synthetic_naip(raster_path)

            gdf = gpd.GeoDataFrame(
                {"parcel_id": ["p001"]},
                geometry=[box(-121.5, 38.5, -121.3, 38.7)],
                crs="EPSG:4326",
            )

            _, chip = next(extract_chips(raster_path, gdf))
            assert chip.min() >= -3.5, f"Min {chip.min()} too low"
            assert chip.max() <= 3.5, f"Max {chip.max()} too high"
            # Most pixels should be within the reasonable norm range
            assert chip.shape == (3, 224, 224)

    def test_parcel_outside_raster_skipped(self) -> None:
        """Parcel entirely outside raster extent should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raster_path = Path(tmpdir) / "test_naip.tif"
            _create_synthetic_naip(raster_path)

            # Parcel far away from the raster
            gdf = gpd.GeoDataFrame(
                {"parcel_id": ["p001"]},
                geometry=[box(-122.0, 37.0, -121.9, 37.1)],
                crs="EPSG:4326",
            )

            chips = list(extract_chips(raster_path, gdf))
            assert len(chips) == 0

    def test_invalid_geometry_skipped(self) -> None:
        """Parcel with None/empty geometry should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raster_path = Path(tmpdir) / "test_naip.tif"
            _create_synthetic_naip(raster_path)

            gdf = gpd.GeoDataFrame(
                {"parcel_id": ["p001", "p002"]},
                geometry=[None, box(-121.5, 38.5, -121.3, 38.7)],
                crs="EPSG:4326",
            )

            chips = list(extract_chips(raster_path, gdf))
            assert len(chips) == 1
            assert chips[0][0] == "p002"

    def test_multiple_parcels_yields_multiple_chips(self) -> None:
        """Multiple parcels should yield multiple chip results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            raster_path = Path(tmpdir) / "test_naip.tif"
            _create_synthetic_naip(raster_path, width=448, height=448)

            gdf = gpd.GeoDataFrame(
                {"parcel_id": ["p001", "p002"]},
                geometry=[
                    box(-121.5, 38.5, -121.4, 38.6),
                    box(-121.4, 38.5, -121.3, 38.6),
                ],
                crs="EPSG:4326",
            )

            chips = list(extract_chips(raster_path, gdf))
            assert len(chips) == 2
            pids = {pid for pid, _ in chips}
            assert pids == {"p001", "p002"}

            for _, chip in chips:
                assert chip.shape == (3, 224, 224)
                assert chip.dtype == np.float32
