"""Shared LightGBM Employment Ratios Regressor — inference-only Python SQLMesh FULL model (blueprinted).

Loads the most recently trained SACOG LightGBM model from the filesystem
cache and predicts per-acre employment sector ratios (ret, off, pub, ind, ag).

- SACOG: training (``brewgis.assessor.parcel_emp_ratios_regressor``) runs
  first in the same plan via the conditional dependency.
- Fresno: no training — the SACOG-trained cache is reused; a missing cache is
  a hard stop (run compare_sacog_basemap first).

Features are read uniformly from ``@{region}.parcel_dasymetric_weights``.
No training logic, no region branching — only data availability differs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator  # noqa: TC003
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.engine_adapter.postgres import PostgresEngineAdapter
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._cache import load_latest_model
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._predict import predict_in_batches
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import EMP_RATIO_TARGETS
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import NUMERIC_FEATURES

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


def _load_emp_model() -> tuple[Any, list[str]]:
    """Load the most recently trained employment-ratio model from cache.

    Only ``emp_ratios__*.pkl`` files are considered, so this regressor can
    never load another model type (du/sqft) by accident. The trained target
    set is variable — zero-sum reference columns are excluded at training
    time — so the stored target list drives the output column mapping.

    Raises RuntimeError if no model is cached or its targets are not a
    subset of ``EMP_RATIO_TARGETS``.
    """
    payload = load_latest_model("emp_ratios")
    if payload is None:
        raise RuntimeError(
            "No cached LightGBM model found for employment ratios regressor. "
            "Run compare_sacog_basemap first to train models in planning/lightgbm_cache/."
        )
    # mypy: the pickled object is a MultiOutputRegressor; attribute access below
    # is safe at runtime.
    model_obj: Any = payload["model"]
    targets = payload["targets"]
    if not set(targets) <= set(EMP_RATIO_TARGETS):
        msg = (
            f"Employment-ratio model targets {targets} are not a subset of "
            f"{EMP_RATIO_TARGETS}. Retrain the emp_ratios regressor "
            "(remove planning/lightgbm_cache/emp_ratios__*.pkl)."
        )
        raise RuntimeError(msg)
    return model_obj, targets


@model(
    "brewgis.@{region}.emp_ratios_regressor",
    kind={"name": ModelKindName.FULL},
    columns={
        "apn": "text",
        "emp_ret_per_acre": "float",
        "emp_off_per_acre": "float",
        "emp_pub_per_acre": "float",
        "emp_ind_per_acre": "float",
        "emp_ag_per_acre": "float",
    },
    audits=[
        ("not_null", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "brewgis.@{region}.parcel_dasymetric_weights",
        "@IF(@train_model != '', brewgis.assessor.parcel_emp_ratios_regressor, brewgis.@{region}.parcel_shim)",
    ],
    blueprints=[
        {
            "region": "sacog",
            "train_model": "brewgis.assessor.parcel_emp_ratios_regressor",
        },
        {"region": "fresno", "train_model": ""},
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Load the SACOG-trained model and predict employment ratios for the region."""
    logger = logging.getLogger(__name__)
    region = context.blueprint_var("region")

    # --- 1. Load the most recently trained EMP model from cache --------------
    model_obj, emp_targets = _load_emp_model()
    logger.info("Loaded EMP model with %d targets", len(emp_targets))

    # --- 2. Learn expected feature columns from the trained model ----------
    expected_cols: list[str] = list(model_obj.estimators_[0].feature_names_in_)  # type: ignore[union-attr]
    logger.info(
        "EMP model expects %d feature columns (%d numeric, %d one-hot, %d ResNet PC)",
        len(expected_cols),
        sum(1 for c in expected_cols if c in NUMERIC_FEATURES),
        sum(1 for c in expected_cols if c.startswith(("lu_", "zone_", "ldc_"))),
        sum(1 for c in expected_cols if c.startswith("pc")),
    )

    # --- 3. Stream inference data from @{region}.parcel_dasymetric_weights --
    dw_table = context.resolve_table(f"brewgis.{region}.parcel_dasymetric_weights")

    pc_cols_sql = ", ".join(f"COALESCE({c}, 0.0) AS {c}" for c in _RESNET_PC_COLS)

    base_query = f"""
        SELECT
            apn,
            lot_size_acres,
            landuse,
            zone,
            COALESCE(land_development_category, 'urban') AS land_development_category,
            COALESCE(residential_building_sqft, 0) AS residential_building_sqft,
            COALESCE(commercial_building_sqft, 0) AS commercial_building_sqft,
            COALESCE(industrial_building_sqft, 0) AS industrial_building_sqft,
            COALESCE(other_building_sqft, 0) AS other_building_sqft,
            COALESCE(total_footprint_sqft, 0) AS total_footprint_sqft,
            COALESCE(building_count, 0) AS building_count,
            COALESCE(footprint_ratio, 0) AS footprint_ratio,
            COALESCE(NULLIF(max_levels, 0), 1) AS max_levels,
            COALESCE(intersection_density, 0) AS intersection_density,
            COALESCE(highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(path_intersection_density, 0) AS path_intersection_density,
            {pc_cols_sql}
        FROM {dw_table}
        ORDER BY apn
    """

    def _stream_region_data(
        ctx: ExecutionContext,
        batch_size: int = 50000,
    ) -> Iterator[pd.DataFrame]:
        """Yield batches of region parcel features for inference."""
        offset = 0
        while True:
            batch = ctx.fetchdf(f"{base_query} LIMIT {batch_size} OFFSET {offset}")
            if len(batch) == 0:
                break
            yield batch
            offset += batch_size

    # --- 4. Feature matrix builder ------------------------------------------
    def _feature_fn(df: pd.DataFrame) -> pd.DataFrame:
        """Build full feature matrix that exactly matches ``expected_cols``.

        Real assessor ``landuse``/``zone`` (SACOG) are one-hot encoded;
        regions without them (Fresno) fall back to ``'XX'``/``'X'`` which
        zeroes every trained category the model handles gracefully.
        """
        df = df.copy()
        df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
        df["zone_prefix"] = df["zone"].fillna("X").str[:1]
        df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
        df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)

        for col in NUMERIC_FEATURES:
            if col in df.columns:
                df[col] = df[col].astype(np.float32)

        # One-hot columns: zero-initialise all, then set known values.
        for col in expected_cols:
            if col.startswith(("lu_", "zone_", "ldc_")):
                df[col] = 0

        # Real assessor landuse/zone one-hots (SACOG). Rows with no
        # landuse/zone (Fresno, or NULL assessor codes) fall back to
        # 'XX'/'X' prefixes, which zero every trained lu_* category and
        # leave only the trained zone_X category hot.
        for col in expected_cols:
            if col.startswith("lu_"):
                df[col] = (df["landuse_prefix"] == col[3:]).astype(int)
            elif col.startswith("zone_"):
                df[col] = (df["zone_prefix"] == col[5:]).astype(int)

        ldc_series = df.get("land_development_category", pd.Series(["urban"] * len(df)))
        for cat in ldc_series.unique():
            col = f"ldc_{cat}"
            if col in df.columns:
                df[col] = (ldc_series == cat).astype(int)

        return df[expected_cols]

    # --- 5. Run inference ---------------------------------------------------
    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_region_data(context),
        model_obj,
        _feature_fn,
    ):
        partial = apns
        # Initialize all targets to 0; only trained targets get non-zero predictions
        for t in EMP_RATIO_TARGETS:
            partial[t] = 0.0
        for i, target in enumerate(emp_targets):
            partial[target] = np.maximum(y_batch[:, i], 0.0).astype(np.float32)
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    logger.info("EMP regressor (%s): %d parcels predicted", region, len(results))

    # --- 6. Yield with batch-size protection --------------------------------
    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
