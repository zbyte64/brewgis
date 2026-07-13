"""LightGBM DU Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-parcel dwelling unit breakdown (du_detsf_sl, du_detsf_ll, du_attsf,
du_mf2to4, du_mf5p) from assessor features + predicted built_form_key.

Replaces the heuristic DU allocation formulas in parcel_du_estimation.sql.
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

LGBM_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "num_leaves": 63,
    "n_estimators": 350,
    "learning_rate": 0.01,
    "min_data_in_leaf": 10,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l1": 0.01,
    "lambda_l2": 10.0,
    "min_gain_to_split": 0.01,
    "verbose": -1,
    "random_state": 42,
}

MIN_R2 = 0.10


def _fetch_du_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference DU data with features for regression training."""
    training_map = context.resolve_table("brewgis.comparison.training_parcel_map")
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
    highway = context.resolve_table(
        "brewgis.assessor.overture_highway_intersection_density"
    )
    path = context.resolve_table("brewgis.assessor.overture_path_intersection_density")

    df = context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ref.du_detsf_sl, ref.du_detsf_ll, ref.du_attsf, ref.du_mf2to4, ref.du_mf5p,
            ap.lot_size_acres, ap.landuse, ap.zone,
            COALESCE(ap.land_development_category, 'standard') AS land_development_category,
            COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
            COALESCE(bs.commercial_building_sqft, 0) AS commercial_building_sqft,
            COALESCE(bs.industrial_building_sqft, 0) AS industrial_building_sqft,
            COALESCE(bs.other_building_sqft, 0) AS other_building_sqft,
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density,
            COALESCE(hw.highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(pw.path_intersection_density, 0) AS path_intersection_density
        FROM public.sac_cnty_region_base_canvas ref
        JOIN {training_map} tpm ON ref.geography_id = tpm.parcel_id
        JOIN {parcels} ap ON tpm.apn = ap.apn
        LEFT JOIN {bldg_sqft} bs ON tpm.apn = bs.apn
        LEFT JOIN {intersection} id ON tpm.apn = id.apn
        LEFT JOIN {highway} hw ON tpm.apn = hw.apn
        LEFT JOIN {path} pw ON tpm.apn = pw.apn
        ORDER BY ap.apn
        """
    )
    return df


def _fetch_inference_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch all assessor parcels with features for inference."""
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
    highway = context.resolve_table(
        "brewgis.assessor.overture_highway_intersection_density"
    )
    path = context.resolve_table("brewgis.assessor.overture_path_intersection_density")

    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            ap.lot_size_acres, ap.landuse, ap.zone,
            COALESCE(ap.land_development_category, 'standard') AS land_development_category,
            COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
            COALESCE(bs.commercial_building_sqft, 0) AS commercial_building_sqft,
            COALESCE(bs.industrial_building_sqft, 0) AS industrial_building_sqft,
            COALESCE(bs.other_building_sqft, 0) AS other_building_sqft,
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density,
            COALESCE(hw.highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(pw.path_intersection_density, 0) AS path_intersection_density
        FROM {parcels} ap
        LEFT JOIN {bldg_sqft} bs ON ap.apn = bs.apn
        LEFT JOIN {intersection} id ON ap.apn = id.apn
        LEFT JOIN {highway} hw ON ap.apn = hw.apn
        LEFT JOIN {path} pw ON ap.apn = pw.apn
        ORDER BY ap.apn
        """
    )


def _extract_top_prefixes(
    train_df: pd.DataFrame, inference_df: pd.DataFrame, col: str, n: int = 20
) -> list[str]:
    """Get top N prefix values from training, plus any seen at inference."""
    train_vals = train_df[col].value_counts().head(n).index.tolist()
    inference_vals = inference_df[col].unique().tolist()
    return sorted(set(train_vals) | set(inference_vals))


def _encode_one_hots(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode categorical features (no built_form_key encoding)."""
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


def _feature_matrix(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
) -> pd.DataFrame:
    """Build full feature matrix with one-hot encoded columns (no built_form_key)."""
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)
    df = _encode_one_hots(df, landuse_prefixes, zone_prefixes, ldev_cats)
    oh_cols = [f"lu_{p}" for p in landuse_prefixes] + [
        f"zone_{p}" for p in zone_prefixes
    ]
    if ldev_cats is not None:
        oh_cols += [f"ldc_{c}" for c in ldev_cats]
    return df[NUMERIC_FEATURES + oh_cols]


@model(
    "brewgis.assessor.parcel_du_regressor",
    kind=dict(name=ModelKindName.FULL),
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
        "brewgis.comparison.training_parcel_map",
        "public.sac_cnty_region_base_canvas",
        "brewgis.assessor.sacog_assessor_parcels",
        "brewgis.assessor.parcel_building_sqft_by_type",
        "brewgis.assessor.overture_intersection_density",
        "brewgis.assessor.overture_highway_intersection_density",
        "brewgis.assessor.overture_path_intersection_density",
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

    inference_df = _fetch_inference_data(context)
    logger.info("LightGBM DU: %d inference parcels", len(inference_df))

    # Include all parcels in training — DU=0 parcels teach the regressor
    # to output zero for non-residential parcels (agricultural, industrial,
    # undeveloped), fixing the previous over-prediction for those categories.
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
        results = inference_df[["apn"]].copy()
        for t in DU_TARGETS:
            results[t] = 0.0
        results["du_total"] = 0.0
        yield results
        return

    # Prepare features for both datasets
    train_df["landuse_prefix"] = train_df["landuse"].fillna("XX").str[:2]
    train_df["zone_prefix"] = train_df["zone"].fillna("X").str[:1]
    inference_df["landuse_prefix"] = inference_df["landuse"].fillna("XX").str[:2]
    inference_df["zone_prefix"] = inference_df["zone"].fillna("X").str[:1]

    landuse_prefixes = _extract_top_prefixes(train_df, inference_df, "landuse_prefix")
    zone_prefixes = sorted(
        set(
            train_df["zone_prefix"].unique().tolist()
            + inference_df["zone_prefix"].unique().tolist()
        )
    )
    ldev_cats = sorted(
        set(
            train_df["land_development_category"].unique().tolist()
            + inference_df["land_development_category"].unique().tolist()
        )
    )

    x_train = _feature_matrix(train_df, landuse_prefixes, zone_prefixes, ldev_cats)
    y_train = train_df[DU_TARGETS].to_numpy()

    # Train or load cached model
    combo = pd.concat([x_train.reset_index(drop=True), pd.DataFrame(y_train)], axis=1)
    data_hash = compute_data_hash(combo)
    model_obj = try_load_cached(data_hash)

    if model_obj is None:
        x_tr, x_va, y_tr, y_va = train_test_split(
            x_train, y_train, test_size=0.2, random_state=42
        )
        base_model = LGBMRegressor(**LGBM_PARAMS)
        model_obj = MultiOutputRegressor(base_model, n_jobs=1)
        model_obj.fit(x_tr, y_tr)
        y_train_pred = model_obj.predict(x_va)

        for i, target in enumerate(DU_TARGETS):
            r2 = r2_score(y_va[:, i], y_train_pred[:, i])
            logger.info("LightGBM DU: %s R² = %.4f", target, r2)

        mean_r2 = r2_score(y_va, y_train_pred, multioutput="uniform_average")
        logger.info("LightGBM DU: mean R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning("LightGBM DU: mean R² %.4f < %.2f", mean_r2, MIN_R2)

        save_model(model_obj, data_hash)
        del y_train_pred
    # free memory
    del x_train
    del y_train

    x_inference = _feature_matrix(
        inference_df, landuse_prefixes, zone_prefixes, ldev_cats
    )
    y_pred = model_obj.predict(x_inference)
    results = inference_df[["apn"]].copy()
    del inference_df
    del x_inference
    for i, target in enumerate(DU_TARGETS):
        results[target] = np.maximum(y_pred[:, i], 0.0).astype(np.float32)
    results["du_total"] = results[DU_TARGETS].sum(axis=1).astype(np.float32)
    del y_pred

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
