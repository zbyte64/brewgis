"""LightGBM Employment Ratios Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-acre employment sector ratios (5 emp_*_per_acre columns) from assessor
features.

Replaces the single emp_alloc_weight heuristic in base_canvas_combined.sql
with category-specific allocation weights, so retail employment is attracted
to retail-heavy parcels, office to office-heavy, etc.
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

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


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
    "objective": "tweedie",
    "tweedie_variance_power": 1.5,
    "metric": "rmse",
    "boosting_type": "gbdt",
    "verbose": -1,
    "random_state": 42,
    "num_leaves": 31,
    "n_estimators": 200,
    "min_gain_to_split": 0.01,
    "min_data_in_leaf": 50,
    "learning_rate": 0.01,
    "lambda_l2": 10,
    "lambda_l1": 0.1,
    "feature_fraction": 0.6,
    "bagging_freq": 5,
    "bagging_fraction": 0.9,
}

MIN_R2 = 0.05
MIN_TRAIN_SAMPLES = 100

EMP_RATIO_TARGETS = [
    "emp_ret_per_acre",
    "emp_off_per_acre",
    "emp_pub_per_acre",
    "emp_ind_per_acre",
    "emp_ag_per_acre",
]


def _fetch_emp_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference employment ratio data with features for regression training."""
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
    features = context.resolve_table("brewgis.assessor.parcel_resnet_features")

    pc_cols_sql = ",\n            ".join(
        f"COALESCE(rf.{c}, 0.0) AS {c}" for c in _RESNET_PC_COLS
    )

    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            COALESCE(ref.emp_ret / NULLIF(ref.acres_parcel_emp, 0), 0) AS emp_ret_per_acre,
            COALESCE(ref.emp_off / NULLIF(ref.acres_parcel_emp, 0), 0) AS emp_off_per_acre,
            COALESCE(ref.emp_pub / NULLIF(ref.acres_parcel_emp, 0), 0) AS emp_pub_per_acre,
            COALESCE(ref.emp_ind / NULLIF(ref.acres_parcel_emp, 0), 0) AS emp_ind_per_acre,
            COALESCE(ref.emp_ag / NULLIF(ref.acres_parcel_emp, 0), 0) AS emp_ag_per_acre,
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
        ORDER BY ap.apn
        """
    )


def _fetch_emp_inference_data(context: ExecutionContext) -> pd.DataFrame:
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
    features = context.resolve_table("brewgis.assessor.parcel_resnet_features")

    pc_cols_sql = ",\n            ".join(
        f"COALESCE(rf.{c}, 0.0) AS {c}" for c in _RESNET_PC_COLS
    )

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
    )


def _extract_top_prefixes(train_df, inference_df, col, n=20):
    train_vals = train_df[col].value_counts().head(n).index.tolist()
    inference_vals = inference_df[col].unique().tolist()
    return sorted(set(train_vals) | set(inference_vals))


def _encode_one_hots(df, landuse_prefixes, zone_prefixes, ldev_cats=None):
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


def _feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats=None):
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
    return df[NUMERIC_FEATURES + oh_cols + _RESNET_PC_COLS]


@model(
    "brewgis.assessor.parcel_emp_ratios_regressor",
    kind=dict(name=ModelKindName.FULL),
    columns={
        "apn": "text",
        "emp_ret_per_acre": "float",
        "emp_off_per_acre": "float",
        "emp_pub_per_acre": "float",
        "emp_ind_per_acre": "float",
        "emp_ag_per_acre": "float",
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
    """Execute employment ratios regressor: train on reference, predict for all parcels."""
    logger = logging.getLogger(__name__)

    df = _fetch_emp_training_data(context)
    logger.info("LightGBM EMP: %d training parcels", len(df))

    inference_df = _fetch_emp_inference_data(context)
    logger.info("LightGBM EMP: %d inference parcels", len(inference_df))

    # Discover target columns at runtime
    emp_targets = [c for c in EMP_RATIO_TARGETS if c in df.columns]
    logger.info("LightGBM EMP: %d target columns: %s", len(emp_targets), emp_targets)

    n_positive = (df[emp_targets].sum(axis=1) > 0).sum()
    logger.info("LightGBM EMP: %d parcels with emp > 0 out of %d", n_positive, len(df))

    if n_positive < MIN_TRAIN_SAMPLES:
        logger.warning(
            "LightGBM EMP: insufficient training data (%d positive)", n_positive
        )
        results = df[["apn"]].copy()
        for t in EMP_RATIO_TARGETS:
            results[t] = 0.0
        yield results
        return

    # Use ALL parcels for training including zeros (~96% zero-inflated)
    # Tweedie objective handles the zero-inflation naturally
    train_df = df.copy()

    # Filter out targets with zero total sum (Tweedie requires sum of labels > 0)
    nonzero_cols = [c for c in emp_targets if train_df[c].sum() > 0]
    excluded = set(emp_targets) - set(nonzero_cols)
    if excluded:
        logger.info("LightGBM EMP: excluded zero-sum columns: %s", excluded)
    emp_targets = nonzero_cols

    if not emp_targets:
        logger.warning("LightGBM EMP: all targets have zero sum, yielding zeros")
        results = df[["apn"]].copy()
        for t in EMP_RATIO_TARGETS:
            results[t] = 0.0
        yield results
        return

    train_df["landuse_prefix"] = train_df["landuse"].fillna("XX").str[:2]
    train_df["zone_prefix"] = train_df["zone"].fillna("X").str[:1]
    inference_df = inference_df.copy()
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
    y_train = train_df[emp_targets].to_numpy()

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

        for i, target in enumerate(emp_targets):
            r2 = r2_score(y_va[:, i], y_train_pred[:, i])
            logger.info("LightGBM EMP: %s R² = %.4f", target, r2)

        mean_r2 = r2_score(y_va, y_train_pred, multioutput="uniform_average")
        logger.info("LightGBM EMP: mean R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning("LightGBM EMP: mean R² %.4f < %.2f", mean_r2, MIN_R2)

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
    # Initialize all targets to 0; only trained targets get non-zero predictions
    for t in EMP_RATIO_TARGETS:
        results[t] = 0.0
    for i, target in enumerate(emp_targets):
        results[target] = np.maximum(y_pred[:, i], 0.0).astype(np.float32)
    del y_pred

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
