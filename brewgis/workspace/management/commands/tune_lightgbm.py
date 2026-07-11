"""One-shot hyperparameter tuning for LightGBM regressors.

Runs against the SACOG reference data in Postgres (requires loaded comparison env).
Prints optimal params for pinning into LGBM_PARAMS in the regressor modules.

Usage: docker compose run --rm django python manage.py tune_lightgbm
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import connection
from lightgbm import LGBMRegressor
from sklearn.model_selection import RandomizedSearchCV

logger = logging.getLogger("tune_lightgbm")

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

DU_TARGETS = ["du_detsf_sl", "du_detsf_ll", "du_attsf", "du_mf2to4", "du_mf5p"]

HP_DISTRIBUTIONS: dict[str, list] = {
    "estimator__num_leaves": [15, 31, 63, 127, 255],
    "estimator__learning_rate": [0.01, 0.03, 0.05, 0.1],
    "estimator__min_data_in_leaf": [5, 10, 20, 50, 100],
    "estimator__feature_fraction": [0.6, 0.7, 0.8, 0.9, 1.0],
    "estimator__bagging_fraction": [0.6, 0.7, 0.8, 0.9, 1.0],
    "estimator__bagging_freq": [1, 5, 10],
    "estimator__lambda_l1": [0.0, 0.01, 0.1, 1.0],
    "estimator__lambda_l2": [0.0, 0.01, 0.1, 1.0, 10.0],
    "estimator__min_gain_to_split": [0.0, 0.01, 0.1],
    "estimator__n_estimators": [200, 500, 1000],
}


def _discover_env_view(cursor, table: str) -> str:
    cursor.execute(
        "SELECT table_schema || '.' || table_name "
        "FROM information_schema.tables "
        "WHERE table_name = %s AND table_schema LIKE '%%__%%'",
        [table],
    )
    rows = cursor.fetchall()
    if not rows:
        raise RuntimeError(f"Cannot find environment view for {table}")
    return min(r[0] for r in rows)


def _extract_top_prefixes(train_df, inference_df, col, n=5):
    train_vals = train_df[col].value_counts().head(n).index.tolist()
    inference_vals = inference_df[col].unique().tolist()
    combined = list(dict.fromkeys(train_vals + inference_vals))
    return combined[: n + len(inference_vals)]


def _feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats):
    """Build feature matrix using pd.concat to avoid fragmentation warnings."""
    landuse_oh = pd.get_dummies(df["landuse_prefix"], prefix="lu")
    landuse_oh = landuse_oh.reindex(
        columns=[f"lu_{p}" for p in landuse_prefixes], fill_value=0
    )
    zone_oh = pd.get_dummies(df["zone_prefix"], prefix="zone")
    zone_oh = zone_oh.reindex(
        columns=[f"zone_{p}" for p in zone_prefixes], fill_value=0
    )
    parts = [df[NUMERIC_FEATURES], landuse_oh, zone_oh]
    if ldev_cats:
        ldev_oh = pd.get_dummies(df["land_development_category"], prefix="ldc")
        ldev_oh = ldev_oh.reindex(columns=[f"ldc_{c}" for c in ldev_cats], fill_value=0)
        parts.append(ldev_oh)
    return pd.concat(parts, axis=1).to_numpy()


def fetch_training_data(cursor, is_du):
    dasymetric = _discover_env_view(cursor, "dasymetric_intersections")
    assessor_parcels = _discover_env_view(cursor, "sacog_assessor_parcels")
    bldg_sqft = _discover_env_view(cursor, "parcel_building_sqft_by_type")
    intersection = _discover_env_view(cursor, "overture_intersection_density")

    if is_du:
        cursor.execute(
            f"""
            SELECT DISTINCT ON (ap.apn)
                ref.du_detsf_sl, ref.du_detsf_ll, ref.du_attsf,
                ref.du_mf2to4, ref.du_mf5p,
                ap.lot_size_acres, ap.landuse, ap.zone,
                COALESCE(ap.land_development_category, 'standard')
                    AS land_development_category,
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
            JOIN {assessor_parcels} ap ON di.apn = ap.apn
            LEFT JOIN {bldg_sqft} bs ON di.apn = bs.apn
            LEFT JOIN {intersection} id ON di.apn = id.apn
            ORDER BY ap.apn
            """
        )
    else:
        cursor.execute(
            f"""
            SELECT DISTINCT ON (ap.apn)
                ap.apn,
                ref.bldg_sqft_detsf_sl, ref.bldg_sqft_detsf_ll, ref.bldg_sqft_attsf,
                ref.bldg_sqft_mf, ref.bldg_sqft_retail_services, ref.bldg_sqft_restaurant,
                ref.bldg_sqft_accommodation, ref.bldg_sqft_arts_entertainment,
                ref.bldg_sqft_other_services, ref.bldg_sqft_office_services,
                ref.bldg_sqft_public_admin, ref.bldg_sqft_education,
                ref.bldg_sqft_medical_services, ref.bldg_sqft_transport_warehousing,
                ref.bldg_sqft_wholesale,
                ref.built_form_key,
                ap.lot_size_acres, ap.landuse, ap.zone,
                COALESCE(ap.land_development_category, 'standard')
                    AS land_development_category,
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
            JOIN {assessor_parcels} ap ON di.apn = ap.apn
            LEFT JOIN {bldg_sqft} bs ON di.apn = bs.apn
            LEFT JOIN {intersection} id ON di.apn = id.apn
            ORDER BY ap.apn
            """
        )

    cols = [desc[0] for desc in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=cols)


def _tune_model(is_du: bool, n_iter: int = 15, cv: int = 3, tune_fraction: float = 0.2):
    """Run hyperparameter search for one model and print results.

    Tunes on the first target column only (params transfer well across targets),
    then trains full MultiOutputRegressor with discovered params.
    Avoids nested parallelism: outer CV folds + inner MultiOutputRegressor both
    at n_jobs=1. LightGBM uses OpenMP internally for tree building.
    """
    label = "DU" if is_du else "SQFT"

    with connection.cursor() as cursor:
        df = fetch_training_data(cursor, is_du)

    logger.info("%s: loaded %d training parcels", label, len(df))

    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]

    if is_du:
        targets = DU_TARGETS
        has_target = df[DU_TARGETS].sum(axis=1) > 0
    else:
        sqft_cols = [c for c in df.columns if c.startswith("bldg_sqft_")]
        targets = sqft_cols
        has_target = df[sqft_cols].sum(axis=1) > 0

    train_df = df[has_target].copy()
    logger.info("%s: %d parcels with target > 0", label, len(train_df))

    landuse_prefixes = _extract_top_prefixes(train_df, train_df, "landuse_prefix")
    zone_prefixes = sorted(train_df["zone_prefix"].unique().tolist())
    ldev_cats = sorted(train_df["land_development_category"].unique().tolist())

    x_all = _feature_matrix(train_df, landuse_prefixes, zone_prefixes, ldev_cats)
    y_all = train_df[targets].to_numpy()

    # Subsample for tuning speed
    n = len(x_all)
    n_tune = min(int(n * tune_fraction), 100_000, n)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, n_tune, replace=False)
    x_tune = x_all[idx]
    y_tune = y_all[idx]

    logger.info(
        "%s: tuning on %d/%d samples, %d iter x %d-fold CV",
        label,
        len(x_tune),
        n,
        n_iter,
        cv,
    )

    # Tune on first target only (params transfer across targets)
    # Avoid nested parallelism: everything at n_jobs=1, LightGBM uses OpenMP
    tuner = LGBMRegressor(
        objective="regression",
        metric="rmse",
        boosting_type="gbdt",
        verbose=-1,
        random_state=42,
        num_threads=0,  # let OpenMP use all cores
    )
    search = RandomizedSearchCV(
        tuner,
        param_distributions={
            k.removeprefix("estimator__"): v for k, v in HP_DISTRIBUTIONS.items()
        },
        n_iter=n_iter,
        cv=cv,
        scoring="neg_root_mean_squared_error",
        n_jobs=1,
        random_state=42,
        verbose=0,
    )

    start = time.time()
    search.fit(x_tune, y_tune[:, 0])  # first target only for tuning
    elapsed = time.time() - start

    best_params = search.best_params_
    score = float(search.best_score_)

    logger.info("%s: tuning done in %.1fs, CV neg-RMSE = %.4f", label, elapsed, score)
    logger.info("%s: best params = %s", label, best_params)

    print(f"\n{'=' * 60}")
    print(f"  {label} OPTIMAL PARAMS")
    print(f"{'=' * 60}")
    for k, v in best_params.items():
        if isinstance(v, float):
            print(f'    "{k}": {v:g},')
        else:
            print(f'    "{k}": {v},')
    print(f"{'=' * 60}\n")


class Command(BaseCommand):
    help = "One-shot hyperparameter tuning for LightGBM DU and SQFT regressors"

    def add_arguments(self, parser):
        parser.add_argument(
            "--n-iter",
            type=int,
            default=15,
            help="Randomized search iterations (default: 15)",
        )
        parser.add_argument(
            "--cv", type=int, default=3, help="Cross-validation folds (default: 3)"
        )
        parser.add_argument(
            "--fraction",
            type=float,
            default=0.2,
            help="Tuning data fraction (default: 0.2)",
        )

    def handle(self, *args, **options):
        print("=" * 60)
        print("  LightGBM Hyperparameter Tuning")
        print("  SACOG Reference Data")
        print("=" * 60)
        print()

        _tune_model(
            is_du=True,
            n_iter=options["n_iter"],
            cv=options["cv"],
            tune_fraction=options["fraction"],
        )
        _tune_model(
            is_du=False,
            n_iter=options["n_iter"],
            cv=options["cv"],
            tune_fraction=options["fraction"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Tuning complete. Copy the params above into LGBM_PARAMS."
            )
        )
