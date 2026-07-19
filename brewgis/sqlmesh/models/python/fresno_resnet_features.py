"""Fresno ResNet-34 Image Feature Extractor — Python SQLMesh FULL model.

Inference-only: loads a SACOG-trained PCA model from planning/pca/ and
extracts 32 PCA-compressed visual features from NAIP aerial imagery for
each Fresno parcel. Does NOT fit a new PCA — reuses existing SACOG model.
"""

from __future__ import annotations

import logging
import pickle
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import torch
from rasterio.warp import transform_bounds
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python.resnet_bft_features import _compute_cog_hash
from brewgis.sqlmesh.models.python.resnet_bft_features import _get_cache_root
from brewgis.sqlmesh.models.python.resnet_bft_features import _infer_batch
from brewgis.sqlmesh.models.python.resnet_bft_features import _load_cached_embeddings
from brewgis.sqlmesh.models.python.resnet_bft_features import _load_resnet_backbone
from brewgis.sqlmesh.models.python.resnet_bft_features import _save_embeddings
from brewgis.workspace.services.chip_extractor import extract_chips
from brewgis.workspace.services.naip_fetcher import download_cog_tiles
from brewgis.workspace.services.naip_fetcher import download_naip_for_parcels

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

_BATCH_SIZE = 2048
_MIN_PCA_SAMPLES = 33  # n_components + 1

_RESNET_COLUMNS: dict[str, str] = {
    "parcel_id": "text",
    "apn": "text",
    **{f"pc{i + 1:02d}": "float" for i in range(32)},
}


@model(
    "brewgis.fresno.parcel_resnet_features",
    kind={"name": ModelKindName.FULL},
    columns=_RESNET_COLUMNS,
    audits=[
        ("not_null", {"columns": "parcel_id"}),
        ("assert_row_count_between", {"min_rows": 100, "max_rows": 100000000}),
    ],
    depends_on=[
        "brewgis.fresno.parcel_shim",
    ],
)
def execute(  # noqa: C901, PLR0912, PLR0915
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Extract ResNet-34 image features for Fresno parcels."""
    logger = logging.getLogger(__name__)

    # Step 1: Load Fresno parcel geometries from parcel_shim
    parcel_table = context.resolve_table("brewgis.fresno.parcel_shim")
    df_parcels = context.fetchdf(
        f"""
        SELECT parcel_id, geometry AS wkb_geometry
        FROM {parcel_table}
        """
    )
    if df_parcels.empty:
        msg = "No parcels found in brewgis.fresno.parcel_shim"
        raise RuntimeError(msg)

    logger.info("Loaded %d parcels from fresno.parcel_shim", len(df_parcels))

    with_wkb = df_parcels.dropna(subset=["wkb_geometry"])

    # Fresno GeoJSON parcels are in EPSG:4326 (WGS84, GeoJSON default)
    gdf = gpd.GeoDataFrame(
        with_wkb,
        geometry=gpd.GeoSeries.from_wkb(with_wkb["wkb_geometry"]),
        crs="EPSG:4326",
    )
    logger.info("Parsed %d valid geometries in EPSG:4326", len(gdf))

    # Already in 4326 — no reprojection needed, but keep the 4326 var for clarity
    gdf_4326 = gdf

    # Step 2: Resolve NAIP COG URL(s) — hard stop on failure
    cog_urls = download_naip_for_parcels(gdf_4326)
    if isinstance(cog_urls, str):
        cog_urls = [cog_urls]
    logger.info("Resolved %d NAIP COG URL(s)", len(cog_urls))

    cog_hash = _compute_cog_hash(cog_urls)

    # Step 2.5: Download COG tiles to local cache for fast raster window reads
    cog_paths = download_cog_tiles(cog_urls)

    # Log COG cache directory size
    cog_files = list(_get_cache_root().glob("cog/*.tif"))
    if cog_files:
        total_mb = sum(f.stat().st_size for f in cog_files) / 1_048_576
        logger.info("COG cache: %d files, %.0f MB", len(cog_files), total_mb)

    # Step 3: Extract chips + ResNet forward pass (or load cached)
    cached = _load_cached_embeddings(cog_hash)

    def _dedup_embeddings(
        embeddings: np.ndarray, pids: list[str]
    ) -> tuple[np.ndarray, list[str]]:
        """Deduplicate parcel embeddings — last tile wins."""
        seen: set[str] = set()
        keep: list[int] = []
        for i in range(len(pids) - 1, -1, -1):
            pid = pids[i]
            if pid not in seen:
                seen.add(pid)
                keep.append(i)
        keep.reverse()
        return embeddings[keep], [pids[i] for i in keep]

    if cached is not None:
        embeddings_np, parcel_ids = cached
        embeddings_np, parcel_ids = _dedup_embeddings(embeddings_np, parcel_ids)
        logger.info(
            "Loaded %d deduplicated cached embeddings (shape %s)",
            len(embeddings_np),
            embeddings_np.shape,
        )
    else:
        device = torch.device("cpu")
        backbone = _load_resnet_backbone(device)
        all_embeddings: list[np.ndarray] = []
        parcel_ids: list[str] = []
        batch_chips: list[np.ndarray] = []
        batch_pids: list[str] = []

        for cog_path in cog_paths:
            tile_name = cog_path.name
            logger.info("Processing COG tile: %s", tile_name)

            # Pre-filter parcels to only those overlapping this tile
            with rasterio.open(str(cog_path)) as src:
                tile_bounds_4326 = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            west, south, east, north = tile_bounds_4326
            tile_parcels = gdf_4326.cx[west:east, south:north]

            if tile_parcels.empty:
                logger.debug("Skipping tile %s: no parcels overlap", tile_name)
                continue

            logger.info(
                "Tile %s: %d overlapping parcels",
                tile_name,
                len(tile_parcels),
            )

            for pid, chip in extract_chips(
                str(cog_path), tile_parcels, parcel_id_col="parcel_id"
            ):
                batch_pids.append(pid)
                batch_chips.append(chip)

                if len(batch_chips) >= _BATCH_SIZE:
                    embeddings = _infer_batch(backbone, batch_chips, device)
                    all_embeddings.append(embeddings)
                    parcel_ids.extend(batch_pids)
                    batch_chips.clear()
                    batch_pids.clear()

        # Last batch
        if batch_chips:
            embeddings = _infer_batch(backbone, batch_chips, device)
            all_embeddings.append(embeddings)
            parcel_ids.extend(batch_pids)

        del backbone
        del batch_chips
        del batch_pids

        if not all_embeddings:
            msg = (
                f"No chips extracted from {len(cog_urls)} NAIP COG tiles for "
                f"{len(gdf_4326)} parcels. Possible CRS or tile extent mismatch."
            )
            raise RuntimeError(msg)

        embeddings_np = np.concatenate(all_embeddings, axis=0)
        logger.info(
            "Extracted %d chip embeddings (shape %s)",
            len(embeddings_np),
            embeddings_np.shape,
        )

        # Deduplicate before saving cache
        embeddings_np, parcel_ids = _dedup_embeddings(embeddings_np, parcel_ids)
        logger.info("Deduplicated to %d unique parcels", len(parcel_ids))

        if len(embeddings_np) < _MIN_PCA_SAMPLES:
            msg = (
                f"Only {len(embeddings_np)} deduplicated chips extracted "
                f"({_MIN_PCA_SAMPLES} required for PCA). "
                f"Insufficient parcel-raster overlap."
            )
            raise RuntimeError(msg)

        _save_embeddings(cog_hash, embeddings_np, parcel_ids)

    # Step 4: Load SACOG-trained PCA from planning/pca/ (inference only — no fitting)
    pca_dir = _get_cache_root() / "pca"
    pkl_files = sorted(
        pca_dir.glob("*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pkl_files:
        msg = (
            "No cached PCA model found in planning/pca/. "
            "Run compare_sacog_basemap first to train the SACOG PCA."
        )
        raise RuntimeError(msg)
    pca_path = pkl_files[0]
    with open(pca_path, "rb") as f:
        pca = pickle.load(f)  # noqa: S301
    logger.info("Loaded SACOG-trained PCA from %s", pca_path.name)

    n_chips = len(embeddings_np)
    features = pca.transform(embeddings_np)  # (N, 32)
    logger.info("Transformed %d samples with PCA (32 components)", n_chips)

    # Step 5: Build result DataFrame
    # Fresno parcels have a 1:1 parcel_id → apn mapping — no training_parcel_map join
    results = pd.DataFrame(
        {
            "parcel_id": parcel_ids,
            "apn": parcel_ids,  # 1:1 mapping for Fresno
        }
    )
    for i in range(32):
        results[_RESNET_PC_COLS[i]] = features[:, i].astype(np.float32)

    results = results[["parcel_id", "apn", *_RESNET_PC_COLS]]
    logger.info("Result: %d rows, %d columns", len(results), len(results.columns))

    yield results
