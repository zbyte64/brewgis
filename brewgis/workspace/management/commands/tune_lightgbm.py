"""One-shot hyperparameter tuning for LightGBM regressors.

Takes its training-data fetch functions, feature matrix, numeric feature list
and target list from the SQLMesh regressor modules themselves. A tuner that
builds its own features searches a model nobody trains, so nothing here may
hold a second copy of the feature contract. Automatically materializes needed
models via SQLMesh before fetching training data.

Usage: docker compose run --rm django python manage.py tune_lightgbm
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np
from django.core.management.base import BaseCommand
from lightgbm import LGBMRegressor
from sklearn.model_selection import RandomizedSearchCV

if TYPE_CHECKING:
    from sqlmesh import Context

from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_SAMPLE_WEIGHT
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_TARGETS
from brewgis.sqlmesh.models.python.parcel_du_regressor import (
    NUMERIC_FEATURES as DU_NUMERIC_FEATURES,
)
from brewgis.sqlmesh.models.python.parcel_du_regressor import (
    _feature_matrix as du_feature_matrix,
)
from brewgis.sqlmesh.models.python.parcel_du_regressor import (
    _fetch_du_training_data as fetch_du_training_data,
)
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import EMP_RATIO_TARGETS
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import (
    NUMERIC_FEATURES as EMP_NUMERIC_FEATURES,
)
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import (
    _feature_matrix as emp_feature_matrix,
)
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import (
    _fetch_emp_training_data as fetch_emp_training_data,
)
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import (
    NUMERIC_FEATURES as SQFT_NUMERIC_FEATURES,
)
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import SQFT_SAMPLE_WEIGHT
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import (
    _feature_matrix as sqft_feature_matrix,
)
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import (
    _fetch_sqft_training_data as fetch_sqft_training_data,
)
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import _get_sqft_targets
from brewgis.workspace.analysis.sqlmesh_runner import get_context
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan

logger = logging.getLogger("tune_lightgbm")

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
    "estimator__n_estimators": [100, 200, 350],
    "estimator__tweedie_variance_power": [1.1, 1.3, 1.5, 1.7, 1.9],
}


def _tune_model(
    context: Context,
    is_du: bool,
    is_emp: bool = False,
    n_iter: int = 15,
    cv: int = 3,
    tune_fraction: float = 0.2,
):
    """Run hyperparameter search for one model and print results.

    Fits a single-output ``LGBMRegressor`` on the model's first target: these
    params go into the shared ``LGBM_PARAMS`` the multi-output trainers reuse
    for every target, so the first target is the proxy being optimised.

    The feature matrix, numeric feature list, target list and training-row
    selection are the ones the corresponding trainer uses, so the search runs
    on the model that actually gets fitted.
    """
    if is_emp:
        label = "EMP"
        df = fetch_emp_training_data(context)
        # Tweedie needs a positive label sum; the trainer drops zero-sum columns.
        targets = [c for c in EMP_RATIO_TARGETS if c in df.columns and df[c].sum() > 0]
        numeric_features = EMP_NUMERIC_FEATURES
        feature_matrix = emp_feature_matrix
        sample_weight = None
        # ~96% of parcels have no employment; the trainer keeps them.
        train_df = df.copy()
    elif is_du:
        label = "DU"
        df = fetch_du_training_data(context)
        targets = DU_TARGETS
        numeric_features = DU_NUMERIC_FEATURES
        feature_matrix = du_feature_matrix
        sample_weight = DU_SAMPLE_WEIGHT
        # DU=0 parcels teach the regressor the zero case, so they stay in.
        train_df = df.copy()
    else:
        label = "SQFT"
        df = fetch_sqft_training_data(context)
        targets = _get_sqft_targets(df)
        numeric_features = SQFT_NUMERIC_FEATURES
        feature_matrix = sqft_feature_matrix
        sample_weight = SQFT_SAMPLE_WEIGHT
        train_df = df[df[targets].sum(axis=1) > 0].copy()

    logger.info("%s: loaded %d training parcels", label, len(df))
    logger.info(
        "%s: tuning on %d parcels, %d targets (%s)",
        label,
        len(train_df),
        len(targets),
        targets[0] if targets else "-",
    )
    logger.info(
        "%s: available features: %s",
        label,
        [c for c in numeric_features if c in df.columns],
    )

    if not targets or train_df.empty:
        logger.warning("%s: no training rows with a usable target, skipping", label)
        return

    ldev_cats = sorted(train_df["land_development_category"].unique().tolist())

    x_all = feature_matrix(train_df, ldev_cats).to_numpy()
    y_all = train_df[targets].to_numpy()
    # The trainers' own row weighting (None for EMP), so the search optimises
    # the loss the fitted model actually minimises.
    w_all = train_df[sample_weight].to_numpy() if sample_weight else None

    n = len(x_all)
    n_tune = min(int(n * tune_fraction), 100_000, n)
    rng = np.random.default_rng(42)
    idx = rng.choice(n, n_tune, replace=False)
    x_tune = x_all[idx]
    y_tune = y_all[idx]
    w_tune = None if w_all is None else w_all[idx]

    logger.info(
        "%s: tuning on %d/%d samples, %d iter x %d-fold CV",
        label,
        len(x_tune),
        n,
        n_iter,
        cv,
    )

    tuner = LGBMRegressor(
        objective="tweedie",
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
    search.fit(x_tune, y_tune[:, 0], sample_weight=w_tune)
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

        # Materialize all upstream SQLMesh models needed by the regressor training queries
        # The + prefix includes transitive dependencies through the SQLMesh DAG.
        tune_selectors: list[str] = [
            "+brewgis.sacog.training_parcel_map",
            "+brewgis.sacog.assessor_parcels",
            "+brewgis.sacog.parcel_building_sqft_by_type",
            "+brewgis.sacog.overture_intersection_density",
            "+brewgis.sacog.hwy_intersection_density",
            "+brewgis.sacog.path_intersection_density",
            "+brewgis.assessor.parcel_resnet_features",
        ]
        logger.info("Materializing upstream models for regressor training data…")
        run_sqlmesh_plan(
            environment="prod",
            select=tune_selectors,
            # restate_models=["brewgis.assessor.parcel_resnet_features"],
        )
        logger.info("Upstream models materialized.")

        sqlmesh_context = get_context()
        logger.info("Starting tuning…")

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
