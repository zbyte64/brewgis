"""LightGBM SQFT Regressor — Python SQLMesh FULL model (Fresno inference).

Loads a SACOG-trained LightGBM multi-output regressor from the model cache and
predicts per-parcel building square footage by type for Fresno parcels.  Uses
features from ``fresno.dasymetric_weights`` (which provides all feature columns
the SACOG model expects).

No training phase — inference only.  Raises RuntimeError if no cached model
exists.
"""

from __future__ import annotations

import logging
import pickle
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlmesh import model
from sqlmesh.core.engine_adapter.postgres import PostgresEngineAdapter
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._cache import _ensure_cache_dir
from brewgis.sqlmesh.models.python._predict import predict_in_batches

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


MODEL_NAME = "brewgis.fresno.sqft_regressor"

SQFT_TARGETS = [
    "bldg_sqft_detsf_sl",
    "bldg_sqft_detsf_ll",
    "bldg_sqft_attsf",
    "bldg_sqft_mf",
    "bldg_sqft_retail_services",
    "bldg_sqft_restaurant",
    "bldg_sqft_accommodation",
    "bldg_sqft_arts_entertainment",
    "bldg_sqft_other_services",
    "bldg_sqft_office_services",
    "bldg_sqft_public_admin",
    "bldg_sqft_education",
    "bldg_sqft_medical_services",
    "bldg_sqft_transport_warehousing",
    "bldg_sqft_wholesale",
]

NUMERIC_FEATURES = [
    "lot_size_acres",
    "intersection_density",
    "highway_intersection_density",
    "path_intersection_density",
    "footprint_ratio",
    "building_count",
    "max_levels",
    "residential_building_sqft",
    "commercial_building_sqft",
    "industrial_building_sqft",
    "other_building_sqft",
    "total_footprint_sqft",
]


def _load_model() -> Any:
    """Load the most recent trained LightGBM SQFT model from cache.

    Raises RuntimeError if no model is found or the loaded model has the wrong
    number of output targets.
    """
    cache_dir = _ensure_cache_dir()
    pkl_files = sorted(
        cache_dir.glob("*.pkl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pkl_files:
        raise RuntimeError(
            "No trained LightGBM SQFT model found in planning/lightgbm_cache/. "
            "Run the SACOG pipeline (compare_sacog_basemap) first to train "
            "the SQFT regressor."
        )
    model_obj = pickle.loads(pkl_files[0].read_bytes())
    n_outputs = len(model_obj.estimators_)
    if n_outputs != len(SQFT_TARGETS):
        raise RuntimeError(
            f"Loaded model has {n_outputs} target(s), expected {len(SQFT_TARGETS)} "
            f"for SQFT. Most recent cache file: {pkl_files[0].name}. "
            "Run the SACOG SQFT regressor pipeline first."
        )
    return model_obj


def _get_model_expected_cols(model_obj: Any) -> list[str]:
    """Extract expected feature names from the loaded LightGBM model.

    MultiOutputRegressor wraps individual LGBMRegressor instances; all share
    the same feature set.
    """
    return model_obj.estimators_[0].booster_.feature_name()


def _encode_one_hots(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode categorical features (no built_form_key encoding).

    Mirrors the SACOG ``parcel_sqft_regressor._encode_one_hots``.
    """
    landuse_oh = pd.get_dummies(df["landuse_prefix"], prefix="lu")
    landuse_oh = landuse_oh.reindex(
        columns=[f"lu_{p}" for p in landuse_prefixes], fill_value=0
    )
    zone_oh = pd.get_dummies(df["zone_prefix"], prefix="zone")
    zone_oh = zone_oh.reindex(
        columns=[f"zone_{p}" for p in zone_prefixes], fill_value=0
    )
    parts = [df, landuse_oh, zone_oh]
    if ldev_cats is not None:
        ldev_oh = pd.get_dummies(df["land_development_category"], prefix="ldc")
        ldev_oh = ldev_oh.reindex(columns=[f"ldc_{c}" for c in ldev_cats], fill_value=0)
        parts.append(ldev_oh)
    return pd.concat(parts, axis=1)


def _build_feature_matrix(
    df: pd.DataFrame,
    expected_cols: list[str],
) -> pd.DataFrame:
    """Build feature matrix matching the SACOG-trained model's expected columns.

    Fresno parcels lack ``landuse`` and ``zone``, so these default to ``"XX"``
    and ``"X"`` respectively.  The one-hot encoder maps them to a "missing"
    category.  ``reindex(columns=expected_cols)`` ensures the output column
    order exactly matches what the model expects; any unexpected one-hot
    categories (not present in the trained model) are silently zeroed.
    """
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)

    # Derive one-hot category sets from expected column names
    lu_prefixes = sorted({c[3:] for c in expected_cols if c.startswith("lu_")})
    zone_prefixes = sorted({c[5:] for c in expected_cols if c.startswith("zone_")})
    ldc_cats = sorted({c[4:] for c in expected_cols if c.startswith("ldc_")}) or None

    df = _encode_one_hots(df, lu_prefixes, zone_prefixes, ldc_cats)

    # Reindex to match exactly; missing cols zero-filled
    return df.reindex(columns=expected_cols, fill_value=0.0).astype(np.float32)


def _stream_inference_data(
    context: ExecutionContext,
    batch_size: int = 50000,
) -> Iterator[pd.DataFrame]:
    """Yield Fresno inference feature batches from ``fresno.dasymetric_weights``.

    Fresno parcels lack ``landuse`` and ``zone`` (supplied as defaults) and
    ``highway_intersection_density`` / ``path_intersection_density`` (set to 0).
    All building-level features come from Overture data pre-aggregated in
    dasymetric_weights.  ResNet PCA columns are passed through when available.
    """
    dasymetric = context.resolve_table("brewgis.fresno.dasymetric_weights")

    query = f"""
        SELECT
            dw.apn,
            'XX'::text AS landuse,
            'X'::text AS zone,
            COALESCE(dw.land_development_category, 'urban')
                AS land_development_category,
            COALESCE(dw.lot_size_acres, 0)::double precision
                AS lot_size_acres,
            0::double precision AS highway_intersection_density,
            0::double precision AS path_intersection_density,
            COALESCE(dw.intersection_density, 0)::double precision
                AS intersection_density,
            COALESCE(dw.footprint_ratio, 0)::double precision
                AS footprint_ratio,
            COALESCE(dw.building_count, 0)::integer AS building_count,
            COALESCE(dw.max_levels, 1)::integer AS max_levels,
            COALESCE(dw.residential_building_sqft, 0)::double precision
                AS residential_building_sqft,
            COALESCE(dw.commercial_building_sqft, 0)::double precision
                AS commercial_building_sqft,
            COALESCE(dw.industrial_building_sqft, 0)::double precision
                AS industrial_building_sqft,
            COALESCE(dw.other_building_sqft, 0)::double precision
                AS other_building_sqft,
            COALESCE(dw.total_footprint_sqft, 0)::double precision
                AS total_footprint_sqft,
            COALESCE(dw.pc01, 0)::double precision AS pc01,
            COALESCE(dw.pc02, 0)::double precision AS pc02,
            COALESCE(dw.pc03, 0)::double precision AS pc03,
            COALESCE(dw.pc04, 0)::double precision AS pc04,
            COALESCE(dw.pc05, 0)::double precision AS pc05,
            COALESCE(dw.pc06, 0)::double precision AS pc06,
            COALESCE(dw.pc07, 0)::double precision AS pc07,
            COALESCE(dw.pc08, 0)::double precision AS pc08,
            COALESCE(dw.pc09, 0)::double precision AS pc09,
            COALESCE(dw.pc10, 0)::double precision AS pc10,
            COALESCE(dw.pc11, 0)::double precision AS pc11,
            COALESCE(dw.pc12, 0)::double precision AS pc12,
            COALESCE(dw.pc13, 0)::double precision AS pc13,
            COALESCE(dw.pc14, 0)::double precision AS pc14,
            COALESCE(dw.pc15, 0)::double precision AS pc15,
            COALESCE(dw.pc16, 0)::double precision AS pc16,
            COALESCE(dw.pc17, 0)::double precision AS pc17,
            COALESCE(dw.pc18, 0)::double precision AS pc18,
            COALESCE(dw.pc19, 0)::double precision AS pc19,
            COALESCE(dw.pc20, 0)::double precision AS pc20,
            COALESCE(dw.pc21, 0)::double precision AS pc21,
            COALESCE(dw.pc22, 0)::double precision AS pc22,
            COALESCE(dw.pc23, 0)::double precision AS pc23,
            COALESCE(dw.pc24, 0)::double precision AS pc24,
            COALESCE(dw.pc25, 0)::double precision AS pc25,
            COALESCE(dw.pc26, 0)::double precision AS pc26,
            COALESCE(dw.pc27, 0)::double precision AS pc27,
            COALESCE(dw.pc28, 0)::double precision AS pc28,
            COALESCE(dw.pc29, 0)::double precision AS pc29,
            COALESCE(dw.pc30, 0)::double precision AS pc30,
            COALESCE(dw.pc31, 0)::double precision AS pc31,
            COALESCE(dw.pc32, 0)::double precision AS pc32
        FROM {dasymetric} dw
        ORDER BY dw.apn
    """

    offset = 0
    while True:
        batch = context.fetchdf(f"{query} LIMIT {batch_size} OFFSET {offset}")
        if len(batch) == 0:
            break
        yield batch
        offset += batch_size


@model(
    MODEL_NAME,
    kind=dict(name=ModelKindName.FULL),
    columns={
        "apn": "text",
        "bldg_sqft_detsf_sl": "float",
        "bldg_sqft_detsf_ll": "float",
        "bldg_sqft_attsf": "float",
        "bldg_sqft_mf": "float",
        "bldg_sqft_retail_services": "float",
        "bldg_sqft_restaurant": "float",
        "bldg_sqft_accommodation": "float",
        "bldg_sqft_arts_entertainment": "float",
        "bldg_sqft_other_services": "float",
        "bldg_sqft_office_services": "float",
        "bldg_sqft_public_admin": "float",
        "bldg_sqft_education": "float",
        "bldg_sqft_medical_services": "float",
        "bldg_sqft_transport_warehousing": "float",
        "bldg_sqft_wholesale": "float",
        "bldg_sqft_total": "float",
    },
    audits=[
        ("not_null", {"columns": "apn"}),
    ],
    depends_on=[
        "brewgis.fresno.dasymetric_weights",
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,
    end: TimeLike,
    execution_time: TimeLike,
    **kwargs: Any,
) -> Iterator[pd.DataFrame]:
    """Execute SQFT regressor: load SACOG model, predict on Fresno parcels."""
    logger = logging.getLogger(__name__)

    model_obj = _load_model()
    expected_cols = _get_model_expected_cols(model_obj)
    logger.info(
        "Fresno SQFT: loaded model with %d expected features and %d targets",
        len(expected_cols),
        len(SQFT_TARGETS),
    )

    def _features(df: pd.DataFrame) -> pd.DataFrame:
        return _build_feature_matrix(df, expected_cols)

    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_inference_data(context),
        model_obj,
        _features,
    ):
        partial = apns
        for i, target in enumerate(SQFT_TARGETS):
            partial[target] = np.maximum(y_batch[:, i], 0.0).astype(np.float32)
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    results["bldg_sqft_total"] = results[SQFT_TARGETS].sum(axis=1).astype(np.float32)

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
