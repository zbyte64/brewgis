"""Fresno Employment Ratios Regressor — inference-only Python SQLMesh FULL model.

Loads a pre-trained SACOG LightGBM model from filesystem cache, runs inference
on Fresno parcels using features from ``fresno.dasymetric_weights``, and yields
per-acre employment sector ratio predictions for 5 categories (ret, off, pub,
ind, ag).

No training phase.  A cache miss (no ``.pkl`` files in ``planning/lightgbm_cache/``)
is a hard stop — raises ``RuntimeError``.
"""

from __future__ import annotations

import logging
import os
import pickle
from collections.abc import Iterator  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
import pandas as pd
from sqlmesh import model
from sqlmesh.core.engine_adapter.postgres import PostgresEngineAdapter
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.models.python._cache import _ensure_cache_dir
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._predict import predict_in_batches
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import EMP_RATIO_TARGETS
from brewgis.sqlmesh.models.python.parcel_emp_ratios_regressor import NUMERIC_FEATURES

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


@model(
    "brewgis.fresno.emp_ratios_regressor",
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
        ("not_null", {"columns": ["apn"]}),
    ],
    depends_on=[
        "brewgis.fresno.dasymetric_weights",
    ],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,
    end: TimeLike,
    execution_time: TimeLike,
    **kwargs: Any,
) -> Iterator[pd.DataFrame]:
    """Load SACOG-trained LightGBM model, predict employment ratios for Fresno."""
    logger = logging.getLogger(__name__)

    # --- 1. Load the most recently trained model from cache -----------------
    cache_dir: Path = _ensure_cache_dir()
    pkl_files = sorted(cache_dir.glob("*.pkl"), key=os.path.getmtime, reverse=True)
    if not pkl_files:
        raise RuntimeError(
            "No cached LightGBM model found for employment ratios regressor. "
            "Run compare_sacog_basemap with --use-assessor-geometry first "
            "to generate models in planning/lightgbm_cache/."
        )
    model_path = pkl_files[0]
    logger.info(
        "Loading EMP model from %s (mtime=%s)",
        model_path.name,
        model_path.stat().st_mtime,
    )

    # mypy: the pickled object is a MultiOutputRegressor, but pickle.loads doesn't
    # carry the type annotation.  The attribute access below is safe at runtime.
    model_obj: Any = pickle.loads(model_path.read_bytes())

    # --- 2. Learn expected feature columns from the trained model ----------
    expected_cols: list[str] = list(model_obj.estimators_[0].feature_names_in_)  # type: ignore[union-attr]
    logger.info(
        "EMP model expects %d feature columns (%d numeric, %d one-hot, %d ResNet PC)",
        len(expected_cols),
        sum(1 for c in expected_cols if c in NUMERIC_FEATURES),
        sum(1 for c in expected_cols if c.startswith(("lu_", "zone_", "ldc_"))),
        sum(1 for c in expected_cols if c.startswith("pc")),
    )

    # --- 3. Stream inference data from fresno.dasymetric_weights ------------
    def _stream_fresno_data(
        ctx: ExecutionContext,
        batch_size: int = 50000,
    ) -> Iterator[pd.DataFrame]:
        """Yield batches of Fresno parcel features for inference."""
        dw_table = ctx.resolve_table("brewgis.fresno.dasymetric_weights")

        pc_cols_sql = ", ".join(f"COALESCE({c}, 0.0) AS {c}" for c in _RESNET_PC_COLS)

        base_query = f"""
            SELECT
                apn,
                lot_size_acres,
                'XX' AS landuse,
                'X' AS zone,
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
                0::double precision AS highway_intersection_density,
                0::double precision AS path_intersection_density,
                {pc_cols_sql}
            FROM {dw_table}
            ORDER BY apn
        """

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

        Fresno parcels lack assessor ``landuse`` and ``zone``, so those are set
        to ``'XX'`` and ``'X'`` respectively.  The SACOG-trained one-hot encoder
        maps these to a "missing" category the model handles gracefully.
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

        df["lu_XX"] = 1  # all Fresno parcels
        df["zone_X"] = 1  # all Fresno parcels

        ldc_series = df.get("land_development_category", pd.Series(["urban"] * len(df)))
        for cat in ldc_series.unique():
            col = f"ldc_{cat}"
            if col in df.columns:
                df[col] = (ldc_series == cat).astype(int)

        return df[expected_cols]

    # --- 5. Run inference ---------------------------------------------------
    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_fresno_data(context),
        model_obj,
        _feature_fn,
    ):
        partial = apns
        # Initialize all targets to 0; only trained targets get non-zero
        for t in EMP_RATIO_TARGETS:
            partial[t] = 0.0
        for i, target in enumerate(EMP_RATIO_TARGETS):
            partial[target] = np.maximum(y_batch[:, i], 0.0).astype(np.float32)
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    logger.info("Fresno EMP regressor: %d parcels predicted", len(results))

    # --- 6. Yield with batch-size protection --------------------------------
    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
