"""Region ResNet-34 image feature adapter — Python SQLMesh FULL model (blueprinted).

Presents per-parcel 32-component PCA features extracted from NAIP aerial
imagery (``parcel_id, apn, pc01..pc32``), consumed by the shared dasymetric
weights model as regressor features.

- SACOG: passes through ``brewgis.assessor.parcel_resnet_features`` — the
  training model that extracts chips from Sacramento imagery, fits the PCA,
  and caches it. Running the SACOG plan therefore (re)trains the PCA.
- Fresno: no cached embeddings — extracts chips from Fresno imagery using the
  same ResNet-34 backbone and applies the SACOG-trained PCA (inference only,
  ``apn = parcel_id``).

The branch is driven by the ``source_table`` blueprint variable: a non-empty
value means "an existing model already produced these features" (SACOG);
an empty value means "compute them from ``@{region}.parcel_shim``" (Fresno).
"""

from __future__ import annotations

import sys

sys.path.append("/app")
import django

django.setup()

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
from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python.resnet_bft_features import _compute_cog_hash
from brewgis.sqlmesh.models.python.resnet_bft_features import _get_cache_root
from brewgis.sqlmesh.models.python.resnet_bft_features import _infer_batch
from brewgis.sqlmesh.models.python.resnet_bft_features import _load_cached_embeddings
from brewgis.sqlmesh.models.python.resnet_bft_features import _load_resnet_backbone
from brewgis.sqlmesh.models.python.resnet_bft_features import _save_embeddings

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


def _fetch_sacog_features(context: ExecutionContext) -> pd.DataFrame:
    """Pass through the SACOG training model's output (already apn-keyed)."""
    table = context.resolve_table("brewgis.assessor.parcel_resnet_features")
    pc_cols_sql = ", ".join(f"COALESCE({c}, 0.0) AS {c}" for c in _RESNET_PC_COLS)
    return context.fetchdf(f"SELECT parcel_id, apn, {pc_cols_sql} FROM {table}")


def _infer_fresno_features(context: ExecutionContext, region: str) -> pd.DataFrame:
    """Extract chips from ``@{region}.parcel_shim`` imagery and apply the cached PCA."""
    logger = logging.getLogger(__name__)

    # Lazy imports — these cascade to Django settings, so import inside the
    # function body to avoid errors when SQLMesh loads models without Django.
    from brewgis.workspace.services.chip_extractor import extract_chips
    from brewgis.workspace.services.naip_fetcher import download_cog_tiles
    from brewgis.workspace.services.naip_fetcher import download_naip_for_parcels

    parcel_table = context.resolve_table(f"brewgis.{region}.parcel_shim")
    df_parcels = context.fetchdf(
        f"""
        SELECT parcel_id, geometry AS wkb_geometry
        FROM {parcel_table}
        """
    )
    if df_parcels.empty:
        msg = f"No parcels found in brewgis.{region}.parcel_shim"
        raise RuntimeError(msg)

    logger.info("Loaded %d parcels from %s.parcel_shim", len(df_parcels), region)

    with_wkb = df_parcels.dropna(subset=["wkb_geometry"])

    # GeoJSON-sourced parcels are EPSG:4326 (WGS84)
    gdf = gpd.GeoDataFrame(
        with_wkb,
        geometry=gpd.GeoSeries.from_wkb(with_wkb["wkb_geometry"]),
        crs="EPSG:4326",
    )
    logger.info("Parsed %d valid geometries in EPSG:4326", len(gdf))

    # Step 2: Resolve NAIP COG URL(s) — hard stop on failure
    cog_urls = download_naip_for_parcels(gdf)
    if isinstance(cog_urls, str):
        cog_urls = [cog_urls]
    logger.info("Resolved %d NAIP COG URL(s)", len(cog_urls))

    cog_hash = _compute_cog_hash(cog_urls)

    # Step 2.5: Download COG tiles to local cache for fast raster window reads
    cog_paths = download_cog_tiles(cog_urls)

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
            tile_parcels = gdf.cx[west:east, south:north]

            if tile_parcels.empty:
                logger.debug("Skipping tile %s: no parcels overlap", tile_name)
                continue

            logger.info("Tile %s: %d overlapping parcels", tile_name, len(tile_parcels))

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
                f"{len(gdf)} parcels. Possible CRS or tile extent mismatch."
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

    features = pca.transform(embeddings_np)  # (N, 32)
    logger.info("Transformed %d samples with PCA (32 components)", len(embeddings_np))

    # Fresno parcels have a 1:1 parcel_id → apn mapping
    results = pd.DataFrame({"parcel_id": parcel_ids, "apn": parcel_ids})
    for i in range(32):
        results[_RESNET_PC_COLS[i]] = features[:, i].astype(np.float32)

    return results[["parcel_id", "apn", *_RESNET_PC_COLS]]


@model(
    "brewgis.@{region}.parcel_resnet_features",
    kind={"name": ModelKindName.FULL},
    columns=_RESNET_COLUMNS,
    audits=[
        ("not_null", {"columns": [exp.to_column("parcel_id")]}),
        ("assert_row_count_between", {"min_rows": 100, "max_rows": 100000000}),
    ],
    depends_on=[
        "@IF(@source_table != '', brewgis.assessor.parcel_resnet_features, brewgis.@{region}.parcel_shim)",
    ],
    blueprints=[
        {"region": "sacog", "source_table": "brewgis.assessor.parcel_resnet_features"},
        {"region": "fresno", "source_table": ""},
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Return SACOG training-model features or infer Fresno features from imagery."""
    logger = logging.getLogger(__name__)
    region = context.blueprint_var("region")
    source_table = context.blueprint_var("source_table", "")

    if source_table:
        results = _fetch_sacog_features(context)
        logger.info("SACOG resnet features: %d rows passed through", len(results))
        yield results
        return

    results = _infer_fresno_features(context, region)
    logger.info("ResNet features for %s: %d rows", region, len(results))
    yield results
