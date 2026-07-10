"""LightGBM BFT Classifier — Python SQLMesh FULL model.

Trains a multiclass gradient-boosted model on reference base canvas data
(~502K parcels, 40 built type classes), then fine-tunes on assessor tier1
sales labels via a 9->39 class mapping. Predicts built_form_key for all
assessor parcels.

Uses bt__ prefix (building type) per UrbanFootprint hierarchy. No pt__
(place type) labels exist in SACOG reference data — only bt__ entries.
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


# ── 39-class SACOG Building Type taxonomy (bt__ prefix = UrbanFootprint BT) ──
# No pt__ (place type) entries exist in the SACOG reference data.
CLASSES = [
    "bt__low_density_detached_residential",
    "bt__medium_density_detached_residential",
    "bt__medium_high_density_detached_residential",
    "bt__very_low_density_detached_residential",
    "bt__rural_residential",
    "bt__medium_density_attached_residential",
    "bt__medium_high_density_attached_residential",
    "bt__high_density_attached_residential",
    "bt__very_high_density_attached_residential",
    "bt__urban_attached_residential",
    "bt__urban_mid_rise_residential",
    "bt__mobile_home_park",
    "bt__farm_home",
    "bt__blank_place_type",
    "bt__communityneighborhood_retail",
    "bt__communityneighborhood_commercial",
    "bt__communityneighborhood_commercialoffice",
    "bt__regional_retail",
    "bt__residentialretail_mixed_use_low",
    "bt__residentialretail_mixed_use_high",
    "bt__moderate_intensity_office",
    "bt__high_intensity_office",
    "bt__cbd_office",
    "bt__light_industrialoffice",
    "bt__hotel",
    "bt__light_industrial",
    "bt__heavy_industrial",
    "bt__agricultural_processingretail_employment",
    "bt__agriculture",
    "bt__publicquasi_public",
    "bt__civic_institution",
    "bt__k_12_school",
    "bt__college_university",
    "bt__medical_facility",
    "bt__park_and_open_space",
    "bt__airport",
    "bt__parking_lot",
    "bt__parking_structure",
    "bt__road",
    "bt__water",
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
    "num_class": len(CLASSES),
    "metric": "multi_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_data_in_leaf": 20,
    "verbose": -1,
    "n_estimators": 50,
    "random_state": 42,
}

REFERENCE_TRAINING_PARAMS: dict[str, Any] = {
    "objective": "multiclass",
    "num_class": len(CLASSES),
    "metric": "multi_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.1,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_data_in_leaf": 20,
    "verbose": -1,
    "n_estimators": 100,
    "random_state": 42,
}

MIN_CLASS_SAMPLES = 200
MIN_MACRO_F1 = 0.30
MIN_TRAIN_SAMPLES = 100


def _discover_env_view(context: ExecutionContext, table: str, base_schema: str) -> str:
    """Find the environment-scoped view for a SQLMesh-managed table.

    In environments like ``sacog_comparison``, SQLMesh creates views under
    ``<model_schema>__<env_name>.<table>``. Queries information_schema at
    runtime to find the view without registering a DAG dependency.

    Raises RuntimeError with actionable message if the view is absent.
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
            f"The comparison environment must be materialized first "
            f"(run compare_sacog_basemap or sqlmesh plan with the "
            f"comparison selectors)."
        )
        raise RuntimeError(msg)
    best = min(rows.iloc[:, 0], key=len)
    return best


def _clean_bft_key(raw: str) -> str:
    """Clean SACOG built_form_key: keep bt__ prefix, strip _sacog suffix."""
    return raw.removesuffix("_sacog")


def _fetch_reference_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch reference SACOG base canvas labels for pre-training.

    Uses _discover_env_view to resolve the dasymetric_intersections crosswalk.
    Fails hard if assessor/Overture/Census tables are missing — no silent
    fallback. Raises RuntimeError if comparison environment is not materialized.
    """
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
            ref.built_form_key,
            ap.lot_size_acres,
            ap.landuse,
            ap.zone,
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
        WHERE ref.built_form_key IS NOT NULL
        ORDER BY ap.apn
        """
    )
    df["built_form_key"] = df["built_form_key"].apply(_clean_bft_key)
    return df


def _fetch_training_data(context: ExecutionContext) -> pd.DataFrame:
    """Fetch tier1 sales labels (9-class) joined with feature tables.

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
        LEFT JOIN {bldg_sqft} bs ON ap.apn = bs.apn
        LEFT JOIN {intersection} id ON ap.apn = id.apn
        ORDER BY ap.apn
        """
    )


def _map_tier1_to_39class(df: pd.DataFrame) -> pd.DataFrame:
    """Map assessor tier1 9-class labels to 39-class SACOG built_form_key.

    Uses lot_size_acres and intersection_density thresholds derived from
    reference data statistics to split coarse classes into fine building types.
    """
    df = df.copy()
    old_9class = df["built_form_key"]

    # Residential — split by lot_size and intersection_density thresholds
    df.loc[
        (old_9class == "detsf_sl") & (df["lot_size_acres"] < 0.15), "built_form_key"
    ] = "bt__medium_density_detached_residential"
    df.loc[
        (old_9class == "detsf_sl") & (df["lot_size_acres"] >= 0.15), "built_form_key"
    ] = "bt__medium_high_density_detached_residential"
    df.loc[
        (old_9class == "detsf_ll") & (df["lot_size_acres"] < 1.0), "built_form_key"
    ] = "bt__low_density_detached_residential"
    df.loc[
        (old_9class == "detsf_ll")
        & (df["lot_size_acres"] >= 1.0)
        & (df["lot_size_acres"] < 5.0),
        "built_form_key",
    ] = "bt__very_low_density_detached_residential"
    df.loc[
        (old_9class == "detsf_ll") & (df["lot_size_acres"] >= 5.0), "built_form_key"
    ] = "bt__rural_residential"
    df.loc[
        (old_9class == "attsf") & (df["intersection_density"] < 50), "built_form_key"
    ] = "bt__medium_density_attached_residential"
    df.loc[
        (old_9class == "attsf") & (df["intersection_density"] >= 50), "built_form_key"
    ] = "bt__medium_high_density_attached_residential"
    df.loc[
        (old_9class == "mf2to4") & (df["intersection_density"] < 50), "built_form_key"
    ] = "bt__medium_density_attached_residential"
    df.loc[
        (old_9class == "mf2to4") & (df["intersection_density"] >= 50), "built_form_key"
    ] = "bt__medium_high_density_attached_residential"
    df.loc[
        (old_9class == "mf5p") & (df["intersection_density"] < 100), "built_form_key"
    ] = "bt__high_density_attached_residential"
    df.loc[
        (old_9class == "mf5p") & (df["intersection_density"] >= 100), "built_form_key"
    ] = "bt__urban_mid_rise_residential"
    df.loc[old_9class == "commercial", "built_form_key"] = (
        "bt__communityneighborhood_retail"
    )
    df.loc[old_9class == "industrial", "built_form_key"] = "bt__light_industrial"
    df.loc[old_9class == "civic", "built_form_key"] = "bt__publicquasi_public"
    df.loc[old_9class == "agricultural", "built_form_key"] = "bt__agriculture"

    return df


def _extract_top_landuse_prefixes(
    train_df: pd.DataFrame, inference_df: pd.DataFrame, n: int = 20
) -> list[str]:
    """Get the top N landuse prefixes from training data, plus any seen at inference."""
    train_prefixes = train_df["landuse_prefix"].value_counts().head(n).index.tolist()
    inference_prefixes = inference_df["landuse_prefix"].unique().tolist()
    return sorted(set(train_prefixes) | set(inference_prefixes))


def _encode_one_hots(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode landuse_prefix, zone_prefix, and optionally land_development_category."""
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
    land_development_categories: list[str] | None = None,
) -> pd.DataFrame:
    """Build the full feature matrix with one-hot encoded columns."""
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)
    df = _encode_one_hots(
        df, landuse_prefixes, zone_prefixes, land_development_categories
    )
    oh_cols = [f"lu_{p}" for p in landuse_prefixes] + [
        f"zone_{p}" for p in zone_prefixes
    ]
    if land_development_categories is not None:
        oh_cols += [f"ldc_{c}" for c in land_development_categories]
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
    ref_df: pd.DataFrame,
    inference_df: pd.DataFrame,
    assessor_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Train 39-class BFT classifier and predict for all parcels.

    Two-stage training:
    1. Pre-train on reference data (502K parcels, 39-class SACOG labels)
    2. Fine-tune on mapped assessor tier1 labels (via _map_tier1_to_39class)

    Falls back to reference-only training when assessor data is unavailable.
    """
    ref_df = ref_df.dropna(subset=["built_form_key"])
    ref_df = ref_df[ref_df["built_form_key"].isin(CLASSES)]

    # Filter reference to classes with minimum samples
    class_counts = ref_df["built_form_key"].value_counts()
    valid_classes = class_counts[class_counts >= MIN_CLASS_SAMPLES].index.tolist()
    dropped = set(CLASSES) - set(valid_classes)
    if dropped:
        logging.getLogger(__name__).info(
            "LightGBM: dropping reference classes with <200 samples: %s",
            sorted(dropped),
        )
    ref_df = ref_df[ref_df["built_form_key"].isin(valid_classes)]

    if ref_df.empty:
        logging.getLogger(__name__).warning(
            "LightGBM: no reference training data — cannot train 39-class model"
        )
        results = inference_df[["apn"]].copy()
        results["built_form_key"] = None
        results["probability"] = None
        return results.astype(object)

    # Create prefix columns for reference and inference
    ref_df = ref_df.copy()
    ref_df["landuse_prefix"] = ref_df["landuse"].fillna("XX").str[:2]
    ref_df["zone_prefix"] = ref_df["zone"].fillna("X").str[:1]
    inference_df = inference_df.copy()
    inference_df["landuse_prefix"] = inference_df["landuse"].fillna("XX").str[:2]
    inference_df["zone_prefix"] = inference_df["zone"].fillna("X").str[:1]

    # Extract prefix & land_development_category vocabularies
    landuse_prefixes = _extract_top_landuse_prefixes(ref_df, inference_df)
    zone_prefixes = sorted(
        set(
            ref_df["zone_prefix"].unique().tolist()
            + inference_df["zone_prefix"].unique().tolist()
        )
    )
    ldev_cats = sorted(
        set(
            ref_df["land_development_category"].unique().tolist()
            + inference_df["land_development_category"].unique().tolist()
        )
    )

    # Build feature matrices for reference
    x_ref = _feature_matrix(ref_df, landuse_prefixes, zone_prefixes, ldev_cats)
    y_ref = ref_df["built_form_key"].map(CLASS_TO_IDX).to_numpy()
    x_inference = _feature_matrix(
        inference_df, landuse_prefixes, zone_prefixes, ldev_cats
    )

    # Handle assessor data if available
    n_mapped = 0
    if assessor_df is not None and len(assessor_df) >= MIN_TRAIN_SAMPLES:
        mapped = _map_tier1_to_39class(assessor_df)
        mapped = mapped[mapped["built_form_key"].isin(CLASSES)]
        # Filter to only classes present in reference training set —
        # init_model requires identical class sets between stages.
        mapped = mapped[mapped["built_form_key"].isin(valid_classes)]
        mapped = mapped.copy()
        mapped["landuse_prefix"] = mapped["landuse"].fillna("XX").str[:2]
        mapped["zone_prefix"] = mapped["zone"].fillna("X").str[:1]
        x_assessor = _feature_matrix(mapped, landuse_prefixes, zone_prefixes, ldev_cats)
        y_assessor = mapped["built_form_key"].map(CLASS_TO_IDX).to_numpy()
        has_assessor = True
        logging.getLogger(__name__).info(
            "LightGBM: %d assessor parcels mapped for fine-tuning",
            len(mapped),
        )
        n_mapped = len(mapped)
    else:
        has_assessor = False
        x_assessor, y_assessor = None, None

    # Data hash for caching
    hash_parts = [x_ref.reset_index(drop=True), pd.DataFrame({"y": y_ref})]
    if has_assessor and x_assessor is not None:
        assert y_assessor is not None
        hash_parts.append(x_assessor.reset_index(drop=True))
        hash_parts.append(pd.DataFrame({"y": y_assessor}))
    combo = pd.concat(hash_parts, axis=1, ignore_index=True)
    data_hash = _compute_data_hash(combo)

    # Try cache
    cached = _try_load_cached_model(context, data_hash)
    if cached is not None:
        model_obj, _, _ = cached
        logging.getLogger(__name__).info(
            "LightGBM: using cached model (hash: %s...)", data_hash[:12]
        )
    else:
        # Stage 1: Pre-train on reference data
        logging.getLogger(__name__).info(
            "LightGBM: pre-training on %d reference parcels",
            len(ref_df),
        )
        model_ref = LGBMClassifier(**REFERENCE_TRAINING_PARAMS)
        model_ref.fit(x_ref, y_ref)
        stage1_model = model_ref

        class_report = classification_report(
            y_ref,
            model_ref.predict(x_ref),
            target_names=[IDX_TO_CLASS[int(i)] for i in sorted(set(y_ref))],
            digits=3,
            zero_division=0.0,
        )
        train_f1 = f1_score(
            y_ref,
            model_ref.predict(x_ref),
            average="macro",
            zero_division=0.0,
        )
        logging.getLogger(__name__).info(
            "LightGBM: reference training complete — macro-F1 on train: %.4f\n%s",
            train_f1,
            class_report,
        )

        # Stage 2: Fine-tune on assessor data
        if has_assessor and x_assessor is not None:
            assert y_assessor is not None
            logging.getLogger(__name__).info(
                "LightGBM: fine-tuning on %d mapped assessor parcels",
                n_mapped,
            )
            x_tr, x_va, y_tr, y_va = train_test_split(
                x_assessor,
                y_assessor,
                test_size=0.2,
                stratify=y_assessor,
                random_state=42,
            )
            model_obj = LGBMClassifier(**TRAINING_PARAMS)
            model_obj.fit(
                x_tr,
                y_tr,
                eval_set=[(x_va, y_va)],
                init_model=stage1_model,
                callbacks=[
                    early_stopping(20, verbose=False),
                    log_evaluation(period=0),
                ],
            )
            y_pred = model_obj.predict(x_va)
            va_classes = [IDX_TO_CLASS[int(i)] for i in sorted(set(y_va))]
            f1_report = classification_report(
                y_va,
                y_pred,
                target_names=va_classes,
                digits=3,
                zero_division=0.0,
            )
            macro_f1 = f1_score(
                y_va,
                y_pred,
                average="macro",
                zero_division=0.0,
            )
            logging.getLogger(__name__).info("LightGBM training report:\n%s", f1_report)
            logging.getLogger(__name__).info(
                "LightGBM: %d training samples from %d classes — macro-F1: %.4f",
                n_mapped,
                len(set(y_assessor)),
                macro_f1,
            )

            if macro_f1 < MIN_MACRO_F1:
                logging.getLogger(__name__).warning(
                    "LightGBM: macro-F1 %.4f < %.2f — model still used",
                    macro_f1,
                    MIN_MACRO_F1,
                )
        else:
            model_obj = stage1_model
            logging.getLogger(__name__).info(
                "LightGBM: no assessor data — using reference-only model"
            )

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
    """Execute LightGBM BFT classifier: train on reference, fine-tune on sales."""
    logging.getLogger(__name__).info("LightGBM: fetching reference training data")

    # Phase 1: reference pre-training data (required — raises if unavailable)
    ref_df = _fetch_reference_training_data(context)
    logging.getLogger(__name__).info(
        "LightGBM: %d reference parcels for pre-training", len(ref_df)
    )

    # Phase 2: assessor tier1 sales for fine-tuning (optional)
    train_df = _fetch_training_data(context)
    logging.getLogger(__name__).info(
        "LightGBM: %d tier1 sales parcels for fine-tuning", len(train_df)
    )

    # Inference data
    inference_df = _fetch_all_parcels(context)
    logging.getLogger(__name__).info(
        "LightGBM: total parcels for inference: %d", len(inference_df)
    )

    results = _train_and_predict(context, ref_df, inference_df, assessor_df=train_df)
    predicted_count = results["built_form_key"].notna().sum()
    logging.getLogger(__name__).info(
        "LightGBM: predicted %d / %d parcels", predicted_count, len(results)
    )

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 500000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
