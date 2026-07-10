"""LightGBM DU Regressor — Python SQLMesh FULL model.

Trains a multi-output LightGBM regressor on reference base canvas data to predict
per-parcel dwelling unit breakdown (du_detsf_sl, du_detsf_ll, du_attsf,
du_mf2to4, du_mf5p) from assessor features + predicted built_form_key.

Replaces the heuristic DU allocation formulas in parcel_du_estimation.sql.
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
    "n_estimators": 200,
    "random_state": 42,
}

MIN_R2 = 0.10


def _discover_env_view(context: ExecutionContext, table: str, base_schema: str) -> str:
    """Find the environment-scoped view for a SQLMesh-managed table.
    Raises RuntimeError if the view is absent.
    """
    rows = context.engine_adapter.fetchdf(
        f"SELECT table_schema || '.' || table_name "
        f"FROM information_schema.tables "
        f"WHERE table_name = '{table}' "
        f"AND table_schema LIKE '%__%'"
    )
    if rows.empty:
        msg = (
            f"Cannot find environment view for {base_schema}.{table}. "
            f"The comparison environment must be materialized first."
        )
        raise RuntimeError(msg)
    return min(rows.iloc[:, 0], key=len)


def _fetch_du_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference DU data with features for regression training."""
    dasymetric = _discover_env_view(
        context, "dasymetric_intersections", "brewgis.comparison"
    )
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )

    df = context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ref.du_detsf_sl, ref.du_detsf_ll, ref.du_attsf, ref.du_mf2to4, ref.du_mf5p,
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
    return df


def _fetch_inference_data(context: ExecutionContext) -> pd.DataFrame:
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
    bft_classes: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode categorical features."""
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
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
    bft_classes: list[str] | None = None,
) -> pd.DataFrame:
    """Build full feature matrix with one-hot encoded columns."""
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


def _compute_data_hash(df: pd.DataFrame) -> str:
    """Compute a content hash of the training data for cache validation."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df).to_numpy().tobytes())
    return h.hexdigest()


def _try_load_cached_model(
    context: ExecutionContext, data_hash: str
) -> tuple[MultiOutputRegressor, list[str], list[str], list[str], list[str]] | None:
    """Load cached model from artifact table."""
    try:
        row = context.fetchdf(
            f"""
            SELECT model_bytes, data_hash, landuse_prefixes, zone_prefixes
            FROM _artifacts.lightgbm_model
            WHERE data_hash = '{data_hash}' AND model_type = 'du_regressor'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if not row.empty:
            model_bytes = row["model_bytes"].iloc[0]
            return (
                pickle.loads(model_bytes),
                row["landuse_prefixes"].iloc[0],
                row["zone_prefixes"].iloc[0],
            )
    except Exception:
        pass
    return None


def _save_model(
    context: ExecutionContext,
    model_obj: MultiOutputRegressor,
    data_hash: str,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
) -> None:
    """Persist the trained model to the artifact table."""
    model_bytes = pickle.dumps(model_obj)
    hex_model = model_bytes.hex()
    landuse_str = ",".join(landuse_prefixes)
    zone_str = ",".join(zone_prefixes)
    context.engine_adapter.execute(
        f"""
        CREATE SCHEMA IF NOT EXISTS _artifacts;
        CREATE TABLE IF NOT EXISTS _artifacts.lightgbm_model (
            id SERIAL PRIMARY KEY,
            model_type TEXT DEFAULT 'du_regressor',
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

    # Filter to parcels with at least one DU target > 0
    has_du = (
        df["du_detsf_sl"]
        + df["du_detsf_ll"]
        + df["du_attsf"]
        + df["du_mf2to4"]
        + df["du_mf5p"]
        > 0
    )
    train_df = df[has_du].copy()
    logger.info("LightGBM DU: %d parcels with DU > 0", len(train_df))

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

    # Extract BFT classes from both datasets
    all_bft = pd.concat([train_df["built_form_key"], inference_df["built_form_key"]])
    bft_classes = sorted(all_bft.dropna().unique().tolist())

    x_train = _feature_matrix(
        train_df, landuse_prefixes, zone_prefixes, ldev_cats, bft_classes
    )
    y_train = train_df[DU_TARGETS].to_numpy()
    x_inference = _feature_matrix(
        inference_df, landuse_prefixes, zone_prefixes, ldev_cats, bft_classes
    )

    # Data hash
    combo = pd.concat([x_train.reset_index(drop=True), pd.DataFrame(y_train)], axis=1)
    data_hash = _compute_data_hash(combo)

    # Try cache
    cached = _try_load_cached_model(context, data_hash)
    if cached is not None:
        model_obj, _, _, _, _ = cached
        logger.info("LightGBM DU: using cached model")
    else:
        x_tr, x_va, y_tr, y_va = train_test_split(
            x_train, y_train, test_size=0.2, random_state=42
        )
        base_model = LGBMRegressor(**LGBM_PARAMS)
        model_obj = MultiOutputRegressor(base_model, n_jobs=-1)
        model_obj.fit(x_tr, y_tr)
        y_pred = model_obj.predict(x_va)

        for i, target in enumerate(DU_TARGETS):
            r2 = r2_score(y_va[:, i], y_pred[:, i])
            logger.info("LightGBM DU: %s R² = %.4f", target, r2)

        mean_r2 = r2_score(y_va, y_pred, multioutput="uniform_average")
        logger.info("LightGBM DU: mean R² = %.4f", mean_r2)

        if mean_r2 < MIN_R2:
            logger.warning("LightGBM DU: mean R² %.4f < %.2f", mean_r2, MIN_R2)

        _save_model(context, model_obj, data_hash, landuse_prefixes, zone_prefixes)

    y_pred = model_obj.predict(x_inference)
    results = inference_df[["apn"]].copy()
    for i, target in enumerate(DU_TARGETS):
        results[target] = np.maximum(y_pred[:, i], 0.0).astype(np.float32)
    results["du_total"] = results[DU_TARGETS].sum(axis=1).astype(np.float32)

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
