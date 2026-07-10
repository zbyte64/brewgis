"""LightGBM SQFT Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-parcel building square footage breakdown by type (15 bldg_sqft_* columns)
from assessor features + predicted built_form_key.

Replaces the heuristic building area formulas in base_canvas_combined.sql.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
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

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


NUMERIC_FEATURES = [
    "lot_size_acres",
    "intersection_density",
    "footprint_ratio",
    "building_count",
    "max_levels",
    "residential_building_sqft",
    "commercial_building_sqft",
    "industrial_building_sqft",
    "other_building_sqft",
    "total_footprint_sqft",
    "centroid_x",
    "centroid_y",
]

LGBM_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_data_in_leaf": 20,
    "verbose": -1,
    "n_estimators": 100,
    "random_state": 42,
}

MIN_R2 = 0.10
MIN_TRAIN_SAMPLES = 100


def _clean_bft_key(raw: str) -> str:
    """Clean SACOG built_form_key: keep bt__ prefix, strip _sacog suffix."""
    if not isinstance(raw, str):
        return raw
    return raw.removesuffix("_sacog")


def _discover_env_view(context: ExecutionContext, table: str, base_schema: str) -> str:
    rows = context.engine_adapter.fetchdf(
        f"SELECT table_schema || '.' || table_name "
        f"FROM information_schema.tables "
        f"WHERE table_name = '{table}' AND table_schema LIKE '%__%'"
    )
    if rows.empty:
        msg = f"Cannot find environment view for {base_schema}.{table}."
        raise RuntimeError(msg)
    return min(rows.iloc[:, 0], key=len)


def _get_sqft_targets(df: pd.DataFrame) -> list[str]:
    """Extract bldg_sqft_* columns from the DataFrame."""
    return [c for c in df.columns if c.startswith("bldg_sqft_")]


def _fetch_sqft_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference building sqft data with features for regression training."""
    dasymetric = _discover_env_view(
        context, "dasymetric_intersections", "brewgis.comparison"
    )
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
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
    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            {cols},
            ref.built_form_key,
            ap.lot_size_acres, ap.landuse, ap.zone,
            COALESCE(ap.land_development_category, 'standard') AS land_development_category,
            ST_X(ST_Transform(ST_Centroid(ap.geometry), 3310)) AS centroid_x,
            ST_Y(ST_Transform(ST_Centroid(ap.geometry), 3310)) AS centroid_y,
            COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
            COALESCE(bs.commercial_building_sqft, 0) AS commercial_building_sqft,
            COALESCE(bs.industrial_building_sqft, 0) AS industrial_building_sqft,
            COALESCE(bs.other_building_sqft, 0) AS other_building_sqft,
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density
        FROM public.sac_cnty_region_base_canvas ref
        JOIN {dasymetric} di ON ref.geography_id = di.parcel_id
        JOIN {parcels} ap ON di.apn = ap.apn
        LEFT JOIN {bldg_sqft} bs ON di.apn = bs.apn
        LEFT JOIN {intersection} id ON di.apn = id.apn
        ORDER BY ap.apn
        """
    )


def _fetch_sqft_inference_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch all assessor parcels with features + built_form_key for inference."""
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
    bft_resolved = context.resolve_table("brewgis.assessor.parcel_bft_resolved")
    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            r.built_form_key,
            ap.lot_size_acres, ap.landuse, ap.zone,
            COALESCE(ap.land_development_category, 'standard') AS land_development_category,
            ST_X(ST_Transform(ST_Centroid(ap.geometry), 3310)) AS centroid_x,
            ST_Y(ST_Transform(ST_Centroid(ap.geometry), 3310)) AS centroid_y,
            COALESCE(bs.residential_building_sqft, 0) AS residential_building_sqft,
            COALESCE(bs.commercial_building_sqft, 0) AS commercial_building_sqft,
            COALESCE(bs.industrial_building_sqft, 0) AS industrial_building_sqft,
            COALESCE(bs.other_building_sqft, 0) AS other_building_sqft,
            COALESCE(bs.total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(bs.building_count, 0) AS building_count,
            COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(bs.max_levels, 1) AS max_levels,
            COALESCE(id.intersection_density, 0) AS intersection_density
        FROM {parcels} ap
        JOIN {bft_resolved} r ON ap.apn = r.apn
        LEFT JOIN {bldg_sqft} bs ON ap.apn = bs.apn
        LEFT JOIN {intersection} id ON ap.apn = id.apn
        ORDER BY ap.apn
        """
    )


def _extract_top_prefixes(train_df, inference_df, col, n=20):
    train_vals = train_df[col].value_counts().head(n).index.tolist()
    inference_vals = inference_df[col].unique().tolist()
    return sorted(set(train_vals) | set(inference_vals))


def _encode_one_hots(
    df, landuse_prefixes, zone_prefixes, ldev_cats=None, bft_classes=None
):
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
    if bft_classes is not None:
        bft_oh = pd.get_dummies(df["built_form_key"], prefix="bft")
        bft_oh = bft_oh.reindex(columns=[f"bft_{c}" for c in bft_classes], fill_value=0)
        parts.append(bft_oh)
    return pd.concat(parts, axis=1)


def _feature_matrix(
    df, landuse_prefixes, zone_prefixes, ldev_cats=None, bft_classes=None
):
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)
    df = _encode_one_hots(df, landuse_prefixes, zone_prefixes, ldev_cats, bft_classes)
    oh_cols = [f"lu_{p}" for p in landuse_prefixes] + [
        f"zone_{p}" for p in zone_prefixes
    ]
    if ldev_cats is not None:
        oh_cols += [f"ldc_{c}" for c in ldev_cats]
    if bft_classes is not None:
        oh_cols += [f"bft_{c}" for c in bft_classes]
    return df[NUMERIC_FEATURES + oh_cols]


def _compute_data_hash(df):
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df).to_numpy().tobytes())
    return h.hexdigest()


def _try_load_cached_model(context, data_hash):
    try:
        row = context.fetchdf(
            f"""
            SELECT model_bytes, data_hash, landuse_prefixes, zone_prefixes
            FROM _artifacts.lightgbm_model
            WHERE data_hash = '{data_hash}' AND model_type = 'sqft_regressor'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if not row.empty:
            return pickle.loads(row["model_bytes"].iloc[0])
    except Exception:
        pass
    return None


def _save_model(context, model_obj, data_hash, landuse_prefixes, zone_prefixes):
    model_bytes = pickle.dumps(model_obj)
    hex_model = model_bytes.hex()
    landuse_str = ",".join(landuse_prefixes)
    zone_str = ",".join(zone_prefixes)
    context.engine_adapter.execute(
        f"""
        CREATE SCHEMA IF NOT EXISTS _artifacts;
        CREATE TABLE IF NOT EXISTS _artifacts.lightgbm_model (
            id SERIAL PRIMARY KEY,
            model_type TEXT DEFAULT 'sqft_regressor',
            model_bytes TEXT,
            data_hash TEXT,
            landuse_prefixes TEXT,
            zone_prefixes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        INSERT INTO _artifacts.lightgbm_model
            (model_bytes, data_hash, landuse_prefixes, zone_prefixes)
        VALUES ('{hex_model}', '{data_hash}', '{landuse_str}', '{zone_str}');
        """
    )


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

    inference_df = _fetch_sqft_inference_data(context)
    logger.info("LightGBM SQFT: %d inference parcels", len(inference_df))

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

    if "built_form_key" in inference_df.columns:
        bft_classes = sorted(inference_df["built_form_key"].dropna().unique())
    else:
        bft_classes = None

    x_train = _feature_matrix(
        train_df, landuse_prefixes, zone_prefixes, ldev_cats, bft_classes
    )
    y_train = train_df[sqft_targets].to_numpy()
    x_inference = _feature_matrix(
        inference_df, landuse_prefixes, zone_prefixes, ldev_cats, bft_classes
    )

    combo = pd.concat([x_train.reset_index(drop=True), pd.DataFrame(y_train)], axis=1)
    data_hash = _compute_data_hash(combo)

    cached = _try_load_cached_model(context, data_hash)
    if cached is not None:
        model_obj = cached
        logger.info("LightGBM SQFT: using cached model")
    else:
        x_tr, x_va, y_tr, y_va = train_test_split(
            x_train, y_train, test_size=0.2, random_state=42
        )
        base_model = LGBMRegressor(**LGBM_PARAMS)
        model_obj = MultiOutputRegressor(base_model, n_jobs=-1)
        model_obj.fit(x_tr, y_tr)
        y_pred = model_obj.predict(x_va)

        for i, target in enumerate(sqft_targets):
            r2 = r2_score(y_va[:, i], y_pred[:, i])
            logger.info("LightGBM SQFT: %s R² = %.4f", target, r2)

        mean_r2 = r2_score(y_va, y_pred, multioutput="uniform_average")
        logger.info("LightGBM SQFT: mean R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning("LightGBM SQFT: mean R² %.4f < %.2f", mean_r2, MIN_R2)

        _save_model(context, model_obj, data_hash, landuse_prefixes, zone_prefixes)

    y_pred = model_obj.predict(x_inference)
    results = inference_df[["apn"]].copy()
    for i, target in enumerate(sqft_targets):
        results[target] = np.maximum(y_pred[:, i], 0.0).astype(np.float32)
    results["bldg_sqft_total"] = results[sqft_targets].sum(axis=1).astype(np.float32)

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
