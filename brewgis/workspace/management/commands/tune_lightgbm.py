"""One-shot hyperparameter tuning for LightGBM regressors.

Uses the exact same training-data fetch functions as the SQLMesh regressor
models — no duplicated logic. Automatically materializes needed models
via SQLMesh before fetching training data.

Usage: docker compose run --rm django python manage.py tune_lightgbm
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from django.core.management.base import BaseCommand
from lightgbm import LGBMRegressor
from sklearn.model_selection import RandomizedSearchCV

from brewgis.sqlmesh.models.python.parcel_du_regressor import (
    _fetch_du_training_data as fetch_du_training_data,
)
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import (
    _fetch_emp_training_data as fetch_emp_training_data,
)
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import (
    _fetch_sqft_training_data as fetch_sqft_training_data,
)
from brewgis.workspace.analysis.sqlmesh_runner import get_context

logger = logging.getLogger("tune_lightgbm")

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


def _extract_top_prefixes(train_df, inference_df, col, n=5):
    train_vals = train_df[col].value_counts().head(n).index.tolist()
    inference_vals = inference_df[col].unique().tolist()
    combined = list(dict.fromkeys(train_vals + inference_vals))
    return combined[: n + len(inference_vals)]


def _feature_matrix(df, landuse_prefixes, zone_prefixes, ldev_cats, features=None):
    """Build feature matrix using pd.concat to avoid fragmentation warnings."""
    if features is None:
        features = [c for c in NUMERIC_FEATURES if c in df.columns]
    landuse_oh = pd.get_dummies(df["landuse_prefix"], prefix="lu")
    landuse_oh = landuse_oh.reindex(
        columns=[f"lu_{p}" for p in landuse_prefixes], fill_value=0
    )
    zone_oh = pd.get_dummies(df["zone_prefix"], prefix="zone")
    zone_oh = zone_oh.reindex(
        columns=[f"zone_{p}" for p in zone_prefixes], fill_value=0
    )
    parts = [df[features], landuse_oh, zone_oh]
    if ldev_cats:
        ldev_oh = pd.get_dummies(df["land_development_category"], prefix="ldc")
        ldev_oh = ldev_oh.reindex(columns=[f"ldc_{c}" for c in ldev_cats], fill_value=0)
        parts.append(ldev_oh)
    return pd.concat(parts, axis=1).to_numpy()


EMP_RATIO_TARGETS = [
    "emp_ret_per_acre",
    "emp_off_per_acre",
    "emp_pub_per_acre",
    "emp_ind_per_acre",
    "emp_ag_per_acre",
]


def _tune_model(
    context,
    is_du: bool,
    is_emp: bool = False,
    n_iter: int = 15,
    cv: int = 3,
    tune_fraction: float = 0.2,
):
    """Run hyperparameter search for one model and print results."""
    if is_emp:
        label = "EMP"
        df = fetch_emp_training_data(context)
        targets = [c for c in EMP_RATIO_TARGETS if c in df.columns]
        objective = "tweedie"
    elif is_du:
        label = "DU"
        df = fetch_du_training_data(context)
        targets = DU_TARGETS
        objective = "regression"
    else:
        label = "SQFT"
        df = fetch_sqft_training_data(context)
        sqft_cols = [c for c in df.columns if c.startswith("bldg_sqft_")]
        targets = sqft_cols
        objective = "regression"

    logger.info("%s: loaded %d training parcels", label, len(df))

    available = [c for c in NUMERIC_FEATURES if c in df.columns]
    logger.info("%s: available features: %s", label, available)

    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    has_target = df[targets].sum(axis=1) > 0
    train_df = df[has_target].copy()
    logger.info("%s: %d parcels with target > 0", label, len(train_df))

    landuse_prefixes = _extract_top_prefixes(train_df, train_df, "landuse_prefix")
    zone_prefixes = sorted(train_df["zone_prefix"].unique().tolist())
    ldev_cats = sorted(train_df["land_development_category"].unique().tolist())

    x_all = _feature_matrix(train_df, landuse_prefixes, zone_prefixes, ldev_cats)
    y_all = train_df[targets].to_numpy()

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

    tuner = LGBMRegressor(
        objective=objective,
        metric="rmse",
        boosting_type="gbdt",
        verbose=-1,
        random_state=42,
        num_threads=0,
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
    search.fit(x_tune, y_tune[:, 0])
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
    help = "One-shot hyperparameter tuning for LightGBM DU, SQFT, and EMP regressors"

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

        sqlmesh_context = get_context()

        _tune_model(
            sqlmesh_context,
            is_du=True,
            n_iter=options["n_iter"],
            cv=options["cv"],
            tune_fraction=options["fraction"],
        )
        _tune_model(
            sqlmesh_context,
            is_du=False,
            n_iter=options["n_iter"],
            cv=options["cv"],
            tune_fraction=options["fraction"],
        )
        _tune_model(
            sqlmesh_context,
            is_du=False,
            is_emp=True,
            n_iter=options["n_iter"],
            cv=options["cv"],
            tune_fraction=options["fraction"],
        )

        print("Tuning complete. Copy the params above into LGBM_PARAMS.")
