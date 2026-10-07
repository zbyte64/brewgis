"""LightGBM DU Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-parcel dwelling unit breakdown (du_detsf_sl, du_detsf_ll, du_attsf,
du_mf2to4, du_mf5p) from assessor features, as dwelling units per square foot of
Overture building area — not actual dwelling units.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputRegressor
from sqlmesh import model
from sqlmesh.core.engine_adapter.postgres import PostgresEngineAdapter
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._cache import compute_data_hash
from brewgis.sqlmesh.models.python._cache import save_model
from brewgis.sqlmesh.models.python._cache import try_load_cached
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._feature_cols import BLDG_CLASS_FALLBACK
from brewgis.sqlmesh.models.python._feature_cols import LDC_FALLBACK
from brewgis.sqlmesh.models.python._feature_cols import MIN_RATIO_DENOMINATOR_SQFT
from brewgis.sqlmesh.models.python._feature_cols import TRAINING_MATCH_ORDER_SQL
from brewgis.sqlmesh.models.python._feature_cols import TRAINING_MATCH_SQL
from brewgis.sqlmesh.models.python._predict import predict_in_batches

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


DU_TARGETS = [
    "du_detsf_sl",
    "du_detsf_ll",
    "du_attsf",
    "du_mf2to4",
    "du_mf5p",
]

# Every DU target is dwelling units per square foot of Overture building area
# (footprint x levels), the single per-parcel stock the regions actually
# observe: the trainer divides by it and serving multiplies by the same column
# from the dasymetric weights. Per-subtype stocks are not used — the reference
# canvas splits multi-family area only as ``bldg_sqft_mf``, and the region
# adapters carry no per-type area at all, so a per-subtype denominator could
# never be reconstructed at serving time. This mirrors the SQFT regressor,
# whose targets are also shares of this same footprint.
DU_RATIO_DENOMINATOR = "total_footprint_sqft"

NUMERIC_FEATURES = [
    "lot_size_acres",
    "intersection_density",
    "highway_intersection_density",
    "path_intersection_density",
    "footprint_ratio",
    "building_count",
    "max_levels",
    "total_footprint_sqft",
]

LGBM_PARAMS: dict[str, Any] = {
    "objective": "tweedie",
    "metric": "tweedie",
    "boosting_type": "gbdt",
    "verbose": -1,
    "random_state": 42,
    "tweedie_variance_power": 1.3,
    "num_leaves": 63,
    "n_estimators": 100,
    "min_gain_to_split": 0.1,
    "min_data_in_leaf": 5,
    "learning_rate": 0.05,
    "lambda_l2": 0,
    "lambda_l1": 1,
    "feature_fraction": 0.9,
    "bagging_freq": 10,
    "bagging_fraction": 0.6,
}

MIN_R2 = 0.10

# Each training row is weighted by the building area serving multiplies its
# ratio by, so the loss tracks dwelling-unit error rather than ratio error.
# Unweighted, a ratio error on a 40,000 sq ft school costs no more than one on
# a house, and the model gives every building class roughly the residential
# ratio: schools, offices and parking structures, which carry no dwelling units
# in the SACOG reference, were served tens of units each.
DU_SAMPLE_WEIGHT = DU_RATIO_DENOMINATOR

# Everything that decides how the cached model is fitted; part of the cache key.
DU_FIT_CONFIG: dict[str, Any] = {
    "params": LGBM_PARAMS,
    "sample_weight": DU_SAMPLE_WEIGHT,
}

# Per-parcel dominant Overture building class (raw taxonomy: house, school,
# retail, church, ... — not the 4-bucket class_category grouping), computed
# in parcel_building_footprints by footprint x levels x overlap area and
# carried through parcel_building_sqft_by_type. COALESCE guards a parcel
# whose bs row is entirely missing (LEFT JOIN miss), matching LDC_FALLBACK's
# role for land_development_category. One-hot encoded below.
_DOMINANT_BUILDING_CLASS_SQL = f"COALESCE(bs.dominant_building_class, '{BLDG_CLASS_FALLBACK}') AS dominant_building_class"


def _fetch_du_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference DU data with features for regression training."""
    training_map = context.resolve_table("brewgis.sacog.training_parcel_map")
    parcels = context.resolve_table("brewgis.sacog.assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.sacog.parcel_building_sqft_by_type")
    intersection = context.resolve_table("brewgis.sacog.overture_intersection_density")
    highway = context.resolve_table("brewgis.sacog.hwy_intersection_density")
    path = context.resolve_table("brewgis.sacog.path_intersection_density")
    features = context.resolve_table("brewgis.assessor.parcel_resnet_features")

    pc_cols_sql = ",\n            ".join(
        f"COALESCE(rf.{c}, 0.0) AS {c}" for c in _RESNET_PC_COLS
    )

    # Dwelling units per square foot of Overture building area. Only rows
    # whose building area reaches MIN_RATIO_DENOMINATOR_SQFT train (WHERE
    # below), matching the SQFT trainer, so the denominator is never ~0.
    target_col = ",\n\t".join(
        f"COALESCE(ref.{t}, 0) / bs.{DU_RATIO_DENOMINATOR} AS {t}" for t in DU_TARGETS
    )

    df = context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            {target_col},
            ap.lot_size_acres,
            COALESCE(ap.land_development_category, '{LDC_FALLBACK}') AS land_development_category,
            {_DOMINANT_BUILDING_CLASS_SQL},
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density,
            COALESCE(hw.highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(pw.path_intersection_density, 0) AS path_intersection_density,
            {pc_cols_sql}
        FROM public.sac_cnty_region_base_canvas ref
        JOIN {training_map} tpm ON ref.geography_id = tpm.parcel_id
        JOIN {parcels} ap ON tpm.apn = ap.apn
        LEFT JOIN {bldg_sqft} bs ON tpm.apn = bs.apn
        LEFT JOIN {intersection} id ON tpm.apn = id.apn
        LEFT JOIN {highway} hw ON tpm.apn = hw.apn
        LEFT JOIN {path} pw ON tpm.apn = pw.apn
        LEFT JOIN {features} rf ON tpm.apn = rf.apn
        WHERE {TRAINING_MATCH_SQL}
          AND bs.{DU_RATIO_DENOMINATOR} >= {MIN_RATIO_DENOMINATOR_SQFT}
        ORDER BY {TRAINING_MATCH_ORDER_SQL}
        """
    )
    return df


def _stream_inference_data(
    context: ExecutionContext,
    batch_size: int = 50000,
) -> Iterator[pd.DataFrame]:
    """Yield inference data in LIMIT/OFFSET batches."""
    parcels = context.resolve_table("brewgis.sacog.assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.sacog.parcel_building_sqft_by_type")
    intersection = context.resolve_table("brewgis.sacog.overture_intersection_density")
    highway = context.resolve_table("brewgis.sacog.hwy_intersection_density")
    path = context.resolve_table("brewgis.sacog.path_intersection_density")
    features = context.resolve_table("brewgis.assessor.parcel_resnet_features")

    pc_cols_sql = ",\n            ".join(
        f"COALESCE(rf.{c}, 0.0) AS {c}" for c in _RESNET_PC_COLS
    )

    query = f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            ap.lot_size_acres,
            COALESCE(ap.land_development_category, '{LDC_FALLBACK}') AS land_development_category,
            {_DOMINANT_BUILDING_CLASS_SQL},
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density,
            COALESCE(hw.highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(pw.path_intersection_density, 0) AS path_intersection_density,
            {pc_cols_sql}
        FROM {parcels} ap
        LEFT JOIN {bldg_sqft} bs ON ap.apn = bs.apn
        LEFT JOIN {intersection} id ON ap.apn = id.apn
        LEFT JOIN {highway} hw ON ap.apn = hw.apn
        LEFT JOIN {path} pw ON ap.apn = pw.apn
        LEFT JOIN {features} rf ON ap.apn = rf.apn
        ORDER BY ap.apn
    """

    offset = 0
    while True:
        batch = context.fetchdf(f"{query} LIMIT {batch_size} OFFSET {offset}")
        if len(batch) == 0:
            break
        yield batch
        offset += batch_size


def _encode_one_hots(
    df: pd.DataFrame,
    ldev_cats: list[str] | None = None,
    bldg_classes: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode categorical features (no built_form_key encoding)."""
    parts = [df]
    if ldev_cats is not None:
        ldev_oh = pd.get_dummies(df["land_development_category"], prefix="ldc")
        ldev_oh = ldev_oh.reindex(columns=[f"ldc_{c}" for c in ldev_cats], fill_value=0)
        parts.append(ldev_oh)
    if bldg_classes is not None:
        bldg_oh = pd.get_dummies(df["dominant_building_class"], prefix="bldg_class")
        bldg_oh = bldg_oh.reindex(
            columns=[f"bldg_class_{c}" for c in bldg_classes], fill_value=0
        )
        parts.append(bldg_oh)
    return pd.concat(parts, axis=1)


def _feature_matrix(
    df: pd.DataFrame,
    ldev_cats: list[str] | None = None,
    bldg_classes: list[str] | None = None,
) -> pd.DataFrame:
    """Build full feature matrix with one-hot encoded columns (no built_form_key)."""
    df = df.copy()
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)
    df = _encode_one_hots(df, ldev_cats, bldg_classes)
    oh_cols = []
    if ldev_cats is not None:
        oh_cols += [f"ldc_{c}" for c in ldev_cats]
    if bldg_classes is not None:
        oh_cols += [f"bldg_class_{c}" for c in bldg_classes]
    return df[NUMERIC_FEATURES + oh_cols + _RESNET_PC_COLS]


@model(
    "brewgis.assessor.parcel_du_regressor",
    kind=dict(name=ModelKindName.FULL),
    description="DU training cache: SACOG LightGBM dwelling units by type, read by the region du_inference models.",
    column_descriptions={
        "apn": "Assessor parcel number (APN) the prediction belongs to.",
        "du_attsf": "Predicted attached single-family dwelling units.",
        "du_detsf_ll": "Predicted detached single-family large-lot dwelling units.",
        "du_detsf_sl": "Predicted detached single-family small-lot dwelling units.",
        "du_mf2to4": "Predicted multi-family 2-4 unit dwelling units.",
        "du_mf5p": "Predicted multi-family 5+ unit dwelling units.",
        "du_total": "Predicted total dwelling units across all types.",
    },
    columns={
        "apn": "text",
        "du_detsf_sl": "float",
        "du_detsf_ll": "float",
        "du_attsf": "float",
        "du_mf2to4": "float",
        "du_mf5p": "float",
        "du_total": "float",
    },
    audits=[
        ("not_null", {"columns": "apn"}),
    ],
    depends_on=[
        "brewgis.sacog.training_parcel_map",
        "public.sac_cnty_region_base_canvas",
        "brewgis.sacog.assessor_parcels",
        "brewgis.sacog.parcel_building_sqft_by_type",
        "brewgis.sacog.overture_intersection_density",
        "brewgis.sacog.hwy_intersection_density",
        "brewgis.sacog.path_intersection_density",
        "brewgis.assessor.parcel_resnet_features",
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,
    end: TimeLike,
    execution_time: TimeLike,
    **kwargs: Any,
) -> Iterator[pd.DataFrame]:
    """Execute DU regressor: train on reference, predict for all parcels."""
    logger = logging.getLogger(__name__)

    df = _fetch_du_training_data(context)
    logger.info("LightGBM DU: %d training parcels from reference", len(df))

    # Every matched parcel with building area trains, DU=0 ones included —
    # they teach the regressor to output zero for non-residential parcels
    # (agricultural, industrial, undeveloped), fixing the previous
    # over-prediction for those categories.
    train_df = df.copy()
    nonzero_count = (train_df[DU_TARGETS].sum(axis=1) > 0).sum()
    zero_count = (train_df[DU_TARGETS].sum(axis=1) == 0).sum()
    logger.info(
        "LightGBM DU: %d training parcels (%d with DU > 0, %d with DU = 0)",
        len(train_df),
        nonzero_count,
        zero_count,
    )

    if len(train_df) < 100:
        logger.warning("LightGBM DU: insufficient training data (%d)", len(train_df))
        apns_parts = [b[["apn"]].copy() for b in _stream_inference_data(context)]
        results = pd.concat(apns_parts, ignore_index=True)
        for t in DU_TARGETS:
            results[t] = 0.0
        results["du_total"] = 0.0
        yield results
        return

    # Prepare features for both datasets
    ldev_cats = sorted(train_df["land_development_category"].unique().tolist())
    bldg_classes = sorted(train_df["dominant_building_class"].unique().tolist())

    x_train = _feature_matrix(train_df, ldev_cats, bldg_classes)
    y_train = train_df[DU_TARGETS].to_numpy()

    # Train or load cached model (type-keyed: one cache namespace per regressor)
    combo = pd.concat([x_train.reset_index(drop=True), pd.DataFrame(y_train)], axis=1)
    data_hash = compute_data_hash(combo, DU_FIT_CONFIG)
    payload = try_load_cached(data_hash, "du")

    if payload is None:
        x_tr, x_va, y_tr, y_va = train_test_split(
            x_train, y_train, test_size=0.2, random_state=42
        )
        base_model = LGBMRegressor(**LGBM_PARAMS)
        model_obj = MultiOutputRegressor(base_model, n_jobs=1)
        model_obj.fit(x_tr, y_tr, sample_weight=x_tr[DU_SAMPLE_WEIGHT].to_numpy())
        # Score what serving emits — dwelling units, the clipped ratio times
        # the parcel's building area — not the ratio itself.
        footprint_va = x_va[DU_RATIO_DENOMINATOR].to_numpy()[:, None]
        du_va = y_va * footprint_va
        du_pred = np.maximum(model_obj.predict(x_va), 0.0) * footprint_va

        for i, target in enumerate(DU_TARGETS):
            r2 = r2_score(du_va[:, i], du_pred[:, i])
            logger.info("LightGBM DU: %s dwelling-unit R² = %.4f", target, r2)

        mean_r2 = r2_score(du_va, du_pred, multioutput="uniform_average")
        logger.info("LightGBM DU: mean dwelling-unit R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning(
                "LightGBM DU: mean dwelling-unit R² %.4f < %.2f", mean_r2, MIN_R2
            )

        save_model(model_obj, data_hash, "du", DU_TARGETS)
        del du_pred
    else:
        model_obj = payload["model"]
    # free memory
    del x_train
    del y_train

    def _features(df: pd.DataFrame) -> pd.DataFrame:
        return _feature_matrix(df, ldev_cats, bldg_classes)

    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_inference_data(context),
        model_obj,
        _features,
    ):
        partial = apns
        for i, target in enumerate(DU_TARGETS):
            partial[target] = np.round(np.maximum(y_batch[:, i], 0.0)).astype(
                np.float32
            )
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    results["du_total"] = results[DU_TARGETS].sum(axis=1).astype(np.float32)

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
