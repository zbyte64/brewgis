"""ResNet-34 Image Feature Extractor -- Python SQLMesh FULL model.

Extracts 32 PCA-compressed visual features from NAIP aerial imagery for each
reference parcel, using a pre-trained ResNet-34 backbone (ImageNet weights,
no fine-tuning). These ``pc01``-``pc32`` columns feed into the LightGBM
DU, SQFT, and employment ratio regressors as additional tabular features.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import torch
from sklearn.decomposition import IncrementalPCA
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName
from torchvision.models import ResNet34_Weights
from torchvision.models import resnet34

from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.workspace.services.chip_extractor import extract_chips
from brewgis.workspace.services.naip_fetcher import download_naip_for_parcels

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

_BATCH_SIZE = 2048
_PCA_CACHE_DIR = Path.home() / ".cache" / "brewgis" / "pca"
_MIN_PCA_SAMPLES = 33  # n_components + 1


def _pca_cache_path(data_hash: str) -> Path:
    """Get filesystem path for cached PCA model."""
    return Path.home() / ".cache" / "brewgis" / "pca" / f"{data_hash}.pkl"


def _compute_cog_hash(cog_urls: list[str]) -> str:
    """Compute a content hash from COG URLs for cache key."""
    h = hashlib.sha256()
    for url in sorted(cog_urls):
        h.update(url.encode())
    return h.hexdigest()


def _load_pca_cache(data_hash: str) -> IncrementalPCA | None:
    """Load cached iPCA from filesystem."""
    cache_path = _pca_cache_path(data_hash)
    if cache_path.exists():
        try:
            return pickle.loads(cache_path.read_bytes())  # noqa: S301
        except (pickle.UnpicklingError, EOFError, ValueError):
            logging.getLogger(__name__).warning(
                "PCA cache read failed for %s", cache_path.name
            )
            cache_path.unlink(missing_ok=True)
    return None


def _save_pca_cache(pca: IncrementalPCA, data_hash: str) -> None:
    """Persist iPCA to filesystem cache."""
    cache_path = _pca_cache_path(data_hash)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(pca))
    tmp.rename(cache_path)
    logging.getLogger(__name__).info("Cached PCA to %s", cache_path.name)


def _embeddings_cache_path(data_hash: str) -> Path:
    """Get filesystem path for cached ResNet embeddings."""
    return Path.home() / ".cache" / "brewgis" / "pca" / f"{data_hash}_embeddings.npz"


def _load_cached_embeddings(
    data_hash: str,
) -> tuple[np.ndarray, list[str]] | None:
    """Load cached embeddings from filesystem. Returns (embeddings, parcel_ids) or None."""
    cache_path = _embeddings_cache_path(data_hash)
    if cache_path.exists():
        try:
            data = np.load(cache_path, allow_pickle=True)
            embeddings = data["embeddings"]
            parcel_ids = data["parcel_ids"].tolist()
        except (ValueError, OSError, KeyError):
            logging.getLogger(__name__).warning(
                "Failed to load cached embeddings, recomputing"
            )
            cache_path.unlink(missing_ok=True)
            return None
        return embeddings, parcel_ids
    return None


def _save_embeddings(
    data_hash: str, embeddings: np.ndarray, parcel_ids: list[str]
) -> None:
    """Persist embeddings to filesystem cache."""
    cache_path = _embeddings_cache_path(data_hash)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, embeddings=embeddings, parcel_ids=parcel_ids)
    tmp.rename(cache_path)
    logging.getLogger(__name__).info(
        "Cached %d embeddings to %s", len(embeddings), cache_path.name
    )


_RESNET_COLUMNS: dict[str, str] = {
    "parcel_id": "text",
    "apn": "text",
    **{f"pc{i + 1:02d}": "float" for i in range(32)},
}


@model(
    "brewgis.assessor.parcel_resnet_features",
    kind={"name": ModelKindName.FULL},
    columns=_RESNET_COLUMNS,
    audits=[
        ("not_null", {"columns": "parcel_id"}),
    ],
    depends_on=[
        "public.sac_cnty_region_existing_land_use_parcels",
        "brewgis.comparison.training_parcel_map",
    ],
)
def execute(  # noqa: C901, PLR0912, PLR0915
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Extract ResNet-34 image features for all reference parcels."""
    logger = logging.getLogger(__name__)

    # Step 1: Load parcel geometries
    df_parcels = context.fetchdf(
        """
        SELECT geography_id AS parcel_id, wkb_geometry AS geometry
        FROM public.sac_cnty_region_existing_land_use_parcels
        """
    )
    if df_parcels.empty:
        msg = "No parcels found in public.sac_cnty_region_existing_land_use_parcels"
        raise RuntimeError(msg)

    logger.info("Loaded %d parcels from reference parcel table", len(df_parcels))

    with_wkb = df_parcels.dropna(subset=["geometry"])

    # Read the actual SRID from PostGIS — SACOG data is SRID 3310 (California Albers)
    srid = context.fetchdf(
        "SELECT ST_SRID(wkb_geometry) AS srid "
        "FROM public.sac_cnty_region_existing_land_use_parcels "
        "WHERE wkb_geometry IS NOT NULL LIMIT 1"
    ).iloc[0, 0]
    if not srid:
        srid = 3310  # SACOG data default: California Albers Equal Area
    crs = f"EPSG:{srid}"
    logger.info("Parcel geometry SRID: %s", crs)

    gdf = gpd.GeoDataFrame(
        with_wkb,
        geometry=gpd.GeoSeries.from_wkb(with_wkb["geometry"]),
        crs=crs,
    )
    logger.info("Parsed %d valid geometries", len(gdf))

    # Reproject to EPSG:4326 for COG chip extraction (NAIP tiles are in WGS84)
    gdf_4326 = gdf.to_crs("EPSG:4326")

    # Step 2: Resolve NAIP COG URL(s) — hard stop on failure
    cog_urls = download_naip_for_parcels(gdf_4326, year=2024)
    if isinstance(cog_urls, str):
        cog_urls = [cog_urls]
    logger.info("Resolved %d NAIP COG URL(s)", len(cog_urls))

    cog_hash = _compute_cog_hash(cog_urls)

    # Step 3: Extract chips + ResNet forward pass (or load cached)
    cached = _load_cached_embeddings(cog_hash)
    if cached is not None:
        embeddings_np, parcel_ids = cached
        logger.info(
            "Loaded %d cached embeddings (shape %s)",
            len(embeddings_np),
            embeddings_np.shape,
        )
    else:
        device = torch.device("cpu")
        backbone = _load_resnet_backbone(device)
        all_embeddings: list[np.ndarray] = []
        parcel_ids = []
        batch_chips: list[np.ndarray] = []
        batch_pids: list[str] = []

        for cog_url in cog_urls:
            tile_name = cog_url.rsplit("/", 1)[-1]
            logger.info("Processing COG tile: %s", tile_name)
            for pid, chip in extract_chips(
                cog_url, gdf_4326, parcel_id_col="parcel_id"
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

        if len(embeddings_np) < _MIN_PCA_SAMPLES:
            msg = (
                f"Only {len(embeddings_np)} chips extracted "
                f"({_MIN_PCA_SAMPLES} required for PCA). "
                f"Insufficient parcel-raster overlap."
            )
            raise RuntimeError(msg)

        _save_embeddings(cog_hash, embeddings_np, parcel_ids)

    # Step 4: Fit/load IncrementalPCA
    pca = _load_pca_cache(cog_hash)
    n_chips = len(embeddings_np)

    if pca is None:
        pca = IncrementalPCA(n_components=32, batch_size=10000)
        pca.fit(embeddings_np)
        _save_pca_cache(pca, cog_hash)
        logger.info("Fitted new PCA on %d samples", n_chips)
    else:
        logger.info("Loaded cached PCA")

    features = pca.transform(embeddings_np)  # (N, 32)

    # Step 5: Build result DataFrame
    results = pd.DataFrame({"parcel_id": parcel_ids})
    for i in range(32):
        results[_RESNET_PC_COLS[i]] = features[:, i].astype(np.float32)

    # Step 6: Join APN from training_parcel_map
    training_map_name = context.resolve_table("brewgis.comparison.training_parcel_map")
    apn_map = context.fetchdf(
        f"""SELECT DISTINCT parcel_id, apn FROM {training_map_name}"""  # noqa: S608
    )
    results = results.merge(apn_map, on="parcel_id", how="left")
    results = results[["parcel_id", "apn", *_RESNET_PC_COLS]]
    logger.info("Result: %d rows, %d columns", len(results), len(results.columns))

    yield results


def _load_resnet_backbone(device: torch.device) -> torch.nn.Module:
    """Load ResNet-34 with ImageNet weights, remove FC layer, set eval."""
    m = resnet34(weights=ResNet34_Weights.IMAGENET1K_V1)
    m.eval()
    backbone = torch.nn.Sequential(*list(m.children())[:-1])
    backbone.to(device)
    backbone.eval()
    return backbone


def _infer_batch(
    backbone: torch.nn.Module,
    chips: list[np.ndarray],
    device: torch.device,
) -> np.ndarray:
    """Run a batch of chips through the ResNet backbone.

    Args:
        backbone: ResNet backbone (no FC layer).
        chips: List of (3, 224, 224) float32 arrays.
        device: Torch device.

    Returns:
        (N, 512) float32 embeddings.
    """
    batch_tensor = torch.from_numpy(np.stack(chips, axis=0)).to(device)
    with torch.no_grad():
        return backbone(batch_tensor).flatten(1).cpu().numpy()
