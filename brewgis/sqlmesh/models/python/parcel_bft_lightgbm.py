"""LightGBM BFT Classifier — Python SQLMesh FULL model.

Trains a multiclass gradient-boosted model on tier1 sales labels, then predicts
built_form_key for all assessor parcels. Drops into the resolved chain between
tier0 and tier3b, replacing tier2 and tier3.
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
from lightgbm import LGBMClassifier
from lightgbm import early_stopping
from lightgbm import log_evaluation
from sklearn.metrics import classification_report
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sqlmesh import model
from sqlmesh.core.engine_adapter.postgres import PostgresEngineAdapter
from sqlmesh.core.model.definition import ModelKindName

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


CLASSES = [
    "detsf_sl",
    "detsf_ll",
    "attsf",
    "mf2to4",
    "mf5p",
    "commercial",
    "industrial",
    "civic",
    "agricultural",
]

CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}
IDX_TO_CLASS = {i: c for c, i in CLASS_TO_IDX.items()}

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

TRAINING_PARAMS: dict[str, Any] = {
    "objective": "multiclass",
    "num_class": 9,
    "metric": "multi_logloss",
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

MIN_CLASS_SAMPLES = 100
MIN_MACRO_F1 = 0.75
MIN_TRAIN_SAMPLES = 100


def _fetch_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch tier1 sales labels joined with feature tables for training.

    Uses context.resolve_table() so table names resolve correctly in SQLMesh
    environments (prod, dev, etc.) where physical names are prefixed.
    """
    tier1_sales = context.resolve_table("brewgis.assessor.parcel_bft_tier1_sales")
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
    return context.fetchdf(
        f"""
        SELECT
            t1.apn,
            t1.built_form_key,
            ap.lot_size_acres,
            ap.landuse,
            ap.zone,
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
        FROM {tier1_sales} t1
        JOIN {parcels} ap ON t1.apn = ap.apn
        LEFT JOIN {bldg_sqft} bs ON t1.apn = bs.apn
        LEFT JOIN {intersection} id ON t1.apn = id.apn
        WHERE t1.built_form_key IS NOT NULL
        """
    )


def _fetch_all_parcels(context: ExecutionContext) -> pd.DataFrame:
    """Fetch ALL parcels with their features for inference.

    Uses context.resolve_table() so table names resolve correctly in SQLMesh
    environments (prod, dev, etc.) where physical names are prefixed.
    """
    parcels = context.resolve_table("brewgis.assessor.sacog_assessor_parcels")
    bldg_sqft = context.resolve_table("brewgis.assessor.parcel_building_sqft_by_type")
    intersection = context.resolve_table(
        "brewgis.assessor.overture_intersection_density"
    )
    return context.fetchdf(
        f"""
        SELECT DISTINCT ON (ap.apn)
            ap.apn,
            ap.lot_size_acres,
            ap.landuse,
            ap.zone,
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
        LEFT JOIN {bldg_sqft} bs ON ap.apn = bs.apn
        LEFT JOIN {intersection} id ON ap.apn = id.apn
        ORDER BY ap.apn
        """
    )


def _extract_top_landuse_prefixes(
    train_df: pd.DataFrame, inference_df: pd.DataFrame, n: int = 20
) -> list[str]:
    """Get the top N landuse prefixes from training data, plus any seen at inference."""
    train_prefixes = train_df["landuse_prefix"].value_counts().head(n).index.tolist()
    inference_prefixes = inference_df["landuse_prefix"].unique().tolist()
    return sorted(set(train_prefixes) | set(inference_prefixes))


def _encode_one_hots(
    df: pd.DataFrame, landuse_prefixes: list[str], zone_prefixes: list[str]
) -> pd.DataFrame:
    """One-hot encode landuse_prefix and zone_prefix with consistent columns."""
    landuse_oh = pd.get_dummies(df["landuse_prefix"], prefix="lu")
    landuse_oh = landuse_oh.reindex(
        columns=[f"lu_{p}" for p in landuse_prefixes], fill_value=0
    )
    zone_oh = pd.get_dummies(df["zone_prefix"], prefix="zone")
    zone_oh = zone_oh.reindex(
        columns=[f"zone_{p}" for p in zone_prefixes], fill_value=0
    )
    return pd.concat([df, landuse_oh, zone_oh], axis=1)


def _feature_matrix(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
) -> pd.DataFrame:
    """Build the full feature matrix with one-hot encoded columns."""
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)
    df = _encode_one_hots(df, landuse_prefixes, zone_prefixes)
    oh_cols = [f"lu_{p}" for p in landuse_prefixes] + [
        f"zone_{p}" for p in zone_prefixes
    ]
    return df[NUMERIC_FEATURES + oh_cols]


def _compute_data_hash(df: pd.DataFrame) -> str:
    """Compute a content hash of the training data for cache validation."""
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(df).to_numpy().tobytes())
    return h.hexdigest()


def _try_load_cached_model(
    context: ExecutionContext, data_hash: str
) -> tuple[LGBMClassifier, list[str], list[str]] | None:
    """Try to load a cached model from the artifact table."""
    try:
        row = context.fetchdf(
            f"""
            SELECT model_bytes, data_hash, landuse_prefixes, zone_prefixes
            FROM _artifacts.lightgbm_model
            WHERE data_hash = '{data_hash}'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if not row.empty:
            model_bytes = row["model_bytes"].iloc[0]
            landuse_prefixes = row["landuse_prefixes"].iloc[0]
            zone_prefixes = row["zone_prefixes"].iloc[0]
            loaded = pickle.loads(model_bytes)
            return loaded, landuse_prefixes, zone_prefixes
    except Exception:
        pass
    return None


def _save_model(
    context: ExecutionContext,
    model_obj: LGBMClassifier,
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
            model_bytes TEXT,
            data_hash TEXT,
            landuse_prefixes TEXT,
            zone_prefixes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        INSERT INTO _artifacts.lightgbm_model (model_bytes, data_hash, landuse_prefixes, zone_prefixes)
        VALUES ('{hex_model}', '{data_hash}', '{landuse_str}', '{zone_str}');
        """
    )


def _train_and_predict(
    context: ExecutionContext,
    train_df: pd.DataFrame,
    inference_df: pd.DataFrame,
) -> pd.DataFrame:
    """Train LightGBM classifier on tier1 labels and predict for all parcels."""
    train_df = train_df.dropna(subset=["built_form_key"])
    train_df = train_df[train_df["built_form_key"].isin(CLASSES)]

    # Filter out classes with too few samples
    class_counts = train_df["built_form_key"].value_counts()
    valid_classes = class_counts[class_counts >= MIN_CLASS_SAMPLES].index.tolist()
    dropped_classes = set(CLASSES) - set(valid_classes)
    if dropped_classes:
        logging.getLogger(__name__).info(
            "LightGBM: dropping low-sample classes: %s", sorted(dropped_classes)
        )
    train_df = train_df[train_df["built_form_key"].isin(valid_classes)]

    if train_df.empty:
        logging.getLogger(__name__).warning("LightGBM: no training data available")
        results = inference_df[["apn"]].copy()
        results["built_form_key"] = None
        results["probability"] = None
        return results.astype(object)

    # Create prefix columns before feature extraction (avoids duplication with _feature_matrix)
    train_df = train_df.copy()
    train_df["landuse_prefix"] = train_df["landuse"].fillna("XX").str[:2]
    train_df["zone_prefix"] = train_df["zone"].fillna("X").str[:1]
    inference_df = inference_df.copy()
    inference_df["landuse_prefix"] = inference_df["landuse"].fillna("XX").str[:2]
    inference_df["zone_prefix"] = inference_df["zone"].fillna("X").str[:1]

    landuse_prefixes = _extract_top_landuse_prefixes(train_df, inference_df)
    zone_prefixes = sorted(
        set(
            train_df["zone_prefix"].unique().tolist()
            + inference_df["zone_prefix"].unique().tolist()
        )
    )

    # Build feature matrices
    x_train = _feature_matrix(train_df, landuse_prefixes, zone_prefixes)
    y_train = train_df["built_form_key"].map(CLASS_TO_IDX).to_numpy()
    x_inference = _feature_matrix(inference_df, landuse_prefixes, zone_prefixes)

    # Data hash for caching
    combo = pd.concat(
        [x_train.reset_index(drop=True), pd.DataFrame({"y": y_train})], axis=1
    )
    data_hash = _compute_data_hash(combo)

    # Try cache
    cached = _try_load_cached_model(context, data_hash)
    if cached is not None:
        model_obj, _, _ = cached
        logging.getLogger(__name__).info("LightGBM: using cached model")
    else:
        x_tr, x_va, y_tr, y_va = train_test_split(
            x_train, y_train, test_size=0.2, stratify=y_train, random_state=42
        )

        model_obj = LGBMClassifier(**TRAINING_PARAMS)
        model_obj.fit(
            x_tr,
            y_tr,
            eval_set=[(x_va, y_va)],
            callbacks=[
                early_stopping(20, verbose=False),
                log_evaluation(period=0),
            ],
        )

        y_pred = model_obj.predict(x_va)
        va_classes = [IDX_TO_CLASS[int(i)] for i in sorted(set(y_va))]
        logging.getLogger(__name__).info(
            "LightGBM validation:\n%s",
            classification_report(
                y_va, y_pred, target_names=va_classes, digits=3, zero_division=0.0
            ),
        )

        macro_f1 = f1_score(y_va, y_pred, average="macro", zero_division=0.0)
        logging.getLogger(__name__).info("LightGBM macro-F1: %.4f", macro_f1)

        if macro_f1 < MIN_MACRO_F1:
            logging.getLogger(__name__).error(
                "LightGBM macro-F1 %.4f < %.2f threshold — model rejected",
                macro_f1,
                MIN_MACRO_F1,
            )
            results = inference_df[["apn"]].copy()
            results["built_form_key"] = None
            results["probability"] = None
            return results.astype(object)

        _save_model(context, model_obj, data_hash, landuse_prefixes, zone_prefixes)

    # Predict for all parcels
    probs = model_obj.predict_proba(x_inference)
    pred_indices = np.argmax(probs, axis=1)
    max_probs = np.max(probs, axis=1)

    results = inference_df[["apn"]].copy()
    results["built_form_key"] = [IDX_TO_CLASS[int(i)] for i in pred_indices]
    results["probability"] = max_probs.astype(np.float32)
    return results


@model(
    "brewgis.assessor.parcel_bft_lightgbm",
    kind=dict(name=ModelKindName.FULL),
    columns={
        "apn": "text",
        "built_form_key": "text",
        "probability": "float",
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
    """Execute LightGBM BFT classifier: train on tier1 labels, predict on all parcels."""
    logging.getLogger(__name__).info("LightGBM: fetching training data")
    train_df = _fetch_training_data(context)

    logging.getLogger(__name__).info(
        "LightGBM: fetching inference data (%d parcels)", len(train_df)
    )
    inference_df = _fetch_all_parcels(context)
    logging.getLogger(__name__).info(
        "LightGBM: total parcels for inference: %d", len(inference_df)
    )

    train_size = len(train_df)
    logging.getLogger(__name__).info("LightGBM: training samples: %d", train_size)

    if train_size < MIN_TRAIN_SAMPLES:
        logging.getLogger(__name__).warning(
            "LightGBM: insufficient training data (%d samples), returning empty",
            train_size,
        )
        results = inference_df[["apn"]].copy()
        results["built_form_key"] = None
        results["probability"] = None
        results = results.astype(object)
    else:
        results = _train_and_predict(context, train_df, inference_df)
        predicted_count = results["built_form_key"].notna().sum()
        logging.getLogger(__name__).info(
            "LightGBM: predicted %d / %d parcels", predicted_count, len(results)
        )

    # Temporarily raise DEFAULT_BATCH_SIZE to avoid splitting the 490K-row DataFrame
    # into 400-row batches (~1226 separate INSERTs). 500000 keeps it as one.
    # Generator try/finally ensures the patch is active during SQLMesh's insert
    # phase (after the yield) and restored on generator exhaustion.
    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000  # type: ignore[assignment]
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original  # type: ignore[assignment]
