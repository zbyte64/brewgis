"""LightGBM SQFT Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-parcel building square footage breakdown by type (15 bldg_sqft_* columns)
from assessor features + predicted built_form_key.

Replaces the heuristic building area formulas in base_canvas_combined.sql.
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
from brewgis.sqlmesh.models.python._predict import predict_in_batches

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


# TODO impermeable surface fraction or sqft
NUMERIC_FEATURES = [
    "lot_size_acres",
    "intersection_density",
    "highway_intersection_density",
    "path_intersection_density",
    "footprint_ratio",
    "building_count",
    "max_levels",
    # CONSIDER: could be presented as a ratio
    "residential_building_sqft",
    "commercial_building_sqft",
    "industrial_building_sqft",
    "other_building_sqft",
    "total_footprint_sqft",
]

LGBM_PARAMS: dict[str, Any] = {
    "objective": "tweedie",
    "metric": "tweedie",
    "boosting_type": "gbdt",
    "verbose": -1,
    "random_state": 42,
    "tweedie_variance_power": 1.3,
    "num_leaves": 31,
    "n_estimators": 200,
    "min_gain_to_split": 0.1,
    "min_data_in_leaf": 20,
    "learning_rate": 0.1,
    "lambda_l2": 1,
    "lambda_l1": 0.01,
    "feature_fraction": 0.8,
    "bagging_freq": 1,
    "bagging_fraction": 0.7,
}

MIN_R2 = 0.10
MIN_TRAIN_SAMPLES = 100


def _clean_bft_key(raw: str) -> str:
    """Clean SACOG built_form_key: keep bt__ prefix, strip _sacog suffix."""
    if not isinstance(raw, str):
        return raw
    return raw.removesuffix("_sacog")


def _get_sqft_targets(df: pd.DataFrame) -> list[str]:
    """Extract bldg_sqft_* columns from the DataFrame."""
    return [c for c in df.columns if c.startswith("bldg_sqft_")]


def _fetch_sqft_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference building sqft data with features for regression training."""
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
    sqft_cols = [
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
    cols = ", ".join(f"ref.{c}" for c in sqft_cols)

    pc_cols_sql = ",\n            ".join(
        f"COALESCE(rf.{c}, 0.0) AS {c}" for c in _RESNET_PC_COLS
    )

    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            {cols},
            ref.built_form_key,
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


def _stream_sqft_inference_data(
    context: ExecutionContext,
    batch_size: int = 50000,
) -> Iterator[pd.DataFrame]:
    """Yield inference data in LIMIT/OFFSET batches."""
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

    query = f"""
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

    offset = 0
    while True:
        batch = context.fetchdf(f"{query} LIMIT {batch_size} OFFSET {offset}")
        if len(batch) == 0:
            break
        yield batch
        offset += batch_size


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
    "brewgis.assessor.parcel_sqft_regressor",
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
    """Execute SQFT regressor: train on reference, predict for all parcels."""
    logger = logging.getLogger(__name__)

    df = _fetch_sqft_training_data(context)
    logger.info("LightGBM SQFT: %d training parcels", len(df))
    df["built_form_key"] = df["built_form_key"].apply(_clean_bft_key)

    # Discover target columns at runtime
    sqft_targets = _get_sqft_targets(df)
    logger.info("LightGBM SQFT: %d target columns: %s", len(sqft_targets), sqft_targets)

    has_sqft = df[sqft_targets].sum(axis=1) > 0
    train_df = df[has_sqft].copy()
    logger.info("LightGBM SQFT: %d parcels with sqft > 0", len(train_df))

    if len(train_df) < MIN_TRAIN_SAMPLES:
        logger.warning("LightGBM SQFT: insufficient training data (%d)", len(train_df))
        results = df[["apn"]].copy()
        for t in sqft_targets:
            results[t] = 0.0
        yield results
        return

    train_df["landuse_prefix"] = train_df["landuse"].fillna("XX").str[:2]
    train_df["zone_prefix"] = train_df["zone"].fillna("X").str[:1]

    landuse_prefixes = sorted(
        train_df["landuse_prefix"].value_counts().head(20).index.tolist()
    )
    zone_prefixes = sorted(train_df["zone_prefix"].unique().tolist())
    ldev_cats = sorted(train_df["land_development_category"].unique().tolist())

    x_train = _feature_matrix(train_df, landuse_prefixes, zone_prefixes, ldev_cats)
    y_train = train_df[sqft_targets].to_numpy()

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

        for i, target in enumerate(sqft_targets):
            r2 = r2_score(y_va[:, i], y_train_pred[:, i])
            logger.info("LightGBM SQFT: %s R² = %.4f", target, r2)

        mean_r2 = r2_score(y_va, y_train_pred, multioutput="uniform_average")
        logger.info("LightGBM SQFT: mean R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning("LightGBM SQFT: mean R² %.4f < %.2f", mean_r2, MIN_R2)

        save_model(model_obj, data_hash)
        del y_train_pred
    # free memory
    del x_train
    del y_train

    def _features(df: pd.DataFrame) -> pd.DataFrame:
        return _feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats)

    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_sqft_inference_data(context),
        model_obj,
        _features,
    ):
        partial = apns
        for i, target in enumerate(sqft_targets):
            partial[target] = np.maximum(y_batch[:, i], 0.0).astype(np.float32)
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    results["bldg_sqft_total"] = results[sqft_targets].sum(axis=1).astype(np.float32)

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
