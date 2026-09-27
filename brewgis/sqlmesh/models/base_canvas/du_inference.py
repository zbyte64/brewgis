"""Shared LightGBM DU Regressor — inference-only Python SQLMesh FULL model (blueprinted).

Loads the most recently trained SACOG LightGBM model from the filesystem
cache and predicts per-parcel DU subtype breakdown for the region.

- SACOG: training (``brewgis.assessor.parcel_du_regressor``) runs first in the
  same plan via the conditional dependency, so the cache is always fresh.
- Fresno: no training — the SACOG-trained cache is reused; a missing cache is
  a hard stop (run compare_sacog_basemap first).

Features are read uniformly from ``@{region}.parcel_dasymetric_weights``; the
predicted ratios are dwelling units per square foot of Overture building area
(``total_footprint_sqft``, footprint x levels) and are scaled back by that same
observed column.
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

from brewgis.sqlmesh.macros.region_blueprints import REGIONS
from brewgis.sqlmesh.models.python._cache import load_latest_model
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._feature_cols import LDC_FALLBACK
from brewgis.sqlmesh.models.python._feature_cols import LDC_PREFIX
from brewgis.sqlmesh.models.python._feature_cols import fitted_feature_names
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_RATIO_DENOMINATOR
from brewgis.sqlmesh.models.python.parcel_du_regressor import DU_TARGETS
from brewgis.sqlmesh.models.python.parcel_du_regressor import NUMERIC_FEATURES

if TYPE_CHECKING:
    from sklearn.multioutput import MultiOutputRegressor
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


def _load_du_model() -> tuple[MultiOutputRegressor, list[str]]:
    """Load the most recently trained DU model from the type-keyed cache.

    Only ``du__*.pkl`` files are considered, so this regressor can never load
    another model type (sqft/emp_ratios) by accident, and artifacts fitted on a
    feature set the current builder cannot produce are skipped.

    Raises RuntimeError if no usable DU model is cached or its targets no
    longer match the expected ``DU_TARGETS``.
    """
    payload = load_latest_model("du", NUMERIC_FEATURES)
    if payload is None:
        raise RuntimeError(
            "No cached LightGBM DU model found for the DU regressor. "
            "Run compare_sacog_basemap first to train models in planning/lightgbm_cache/."
        )
    # mypy: the pickled object is a MultiOutputRegressor; attribute access below
    # is safe at runtime.
    model_obj: Any = payload["model"]
    targets = payload["targets"]
    if targets != DU_TARGETS:
        msg = (
            f"DU model target mismatch: cache has {targets}, expected {DU_TARGETS}. "
            "Retrain the DU regressor (remove planning/lightgbm_cache/du__*.pkl)."
        )
        raise RuntimeError(msg)
    return model_obj, targets


_TRAIN_MODEL = {
    "sacog": "brewgis.assessor.parcel_du_regressor",
    "fresno": "",
}


def _base_query(dw_table: str) -> str:
    """Build the streaming query: dw features plus the ratio denominator.

    ``total_footprint_sqft`` is Overture building area (footprint x levels) —
    the same quantity the trainer divides by, so the served prediction is that
    ratio times an observed per-parcel number.
    """
    pc_cols_sql = ", ".join(f"COALESCE({c}, 0.0) AS {c}" for c in _RESNET_PC_COLS)
    return f"""
        SELECT
            dw.apn,
            dw.lot_size_acres,
            COALESCE(dw.land_development_category, '{LDC_FALLBACK}') AS land_development_category,
            COALESCE(dw.{DU_RATIO_DENOMINATOR}, 0) AS {DU_RATIO_DENOMINATOR},
            COALESCE(dw.building_count, 0) AS building_count,
            COALESCE(dw.footprint_ratio, 0) AS footprint_ratio,
            COALESCE(dw.max_levels, 1) AS max_levels,
            COALESCE(dw.intersection_density, 0) AS intersection_density,
            COALESCE(dw.highway_intersection_density, 0) AS highway_intersection_density,
            COALESCE(dw.path_intersection_density, 0) AS path_intersection_density,
            {pc_cols_sql}
        FROM {dw_table} dw
        ORDER BY dw.apn
    """


@model(
    "brewgis.@{region}.du_inference",
    kind={"name": ModelKindName.FULL},
    description="LightGBM prediction of dwelling units by type for region parcels, from the SACOG-trained cache.",
    column_descriptions={
        "apn": "Assessor parcel number (APN) the prediction belongs to.",
        "du_detsf_sl": "Predicted detached single-family small-lot dwelling units.",
        "du_detsf_ll": "Predicted detached single-family large-lot dwelling units.",
        "du_attsf": "Predicted attached single-family dwelling units.",
        "du_mf2to4": "Predicted multi-family 2-4 unit dwelling units.",
        "du_mf5p": "Predicted multi-family 5+ unit dwelling units.",
        "du_total": "Predicted total dwelling units across all types.",
    },
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
        ("not_null", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "brewgis.@{region}.parcel_dasymetric_weights",
        "@IF(@train_model != '', brewgis.assessor.parcel_du_regressor, brewgis.@{region}.parcel_shim)",
    ],
    blueprints=[{"region": r, "train_model": _TRAIN_MODEL[r]} for r in REGIONS],
)
def execute(
    context: ExecutionContext,
    start: TimeLike,  # noqa: ARG001
    end: TimeLike,  # noqa: ARG001
    execution_time: TimeLike,  # noqa: ARG001
    **kwargs: Any,  # noqa: ARG001
) -> Iterator[pd.DataFrame]:
    """Load the SACOG-trained model and predict DU for the region's parcels."""
    logger = logging.getLogger(__name__)
    region = context.blueprint_var("region")

    # --- 1. Load the most recently trained DU model from cache ---------------
    model_obj, du_targets = _load_du_model()
    logger.info("Loaded DU model with %d targets", len(du_targets))

    # --- 2. Learn expected feature columns from the trained model ----------
    # load_latest_model only hands back artifacts the current feature set can build.
    expected_cols = fitted_feature_names(model_obj)
    assert expected_cols is not None
    logger.info(
        "DU model expects %d feature columns (%d numeric, %d one-hot, %d ResNet PC)",
        len(expected_cols),
        sum(1 for c in expected_cols if c in NUMERIC_FEATURES),
        sum(1 for c in expected_cols if c.startswith(LDC_PREFIX)),
        sum(1 for c in expected_cols if c.startswith("pc")),
    )

    # --- 3. Stream inference data from @{region}.parcel_dasymetric_weights --
    dw_table = context.resolve_table(f"brewgis.{region}.parcel_dasymetric_weights")
    base_query = _base_query(dw_table)

    def _stream_region_data(
        ctx: ExecutionContext,
        batch_size: int = 50000,
    ):
        """Yield batches of region parcel features for inference."""
        offset = 0
        while True:
            batch = ctx.fetchdf(f"{base_query} LIMIT {batch_size} OFFSET {offset}")
            if len(batch) == 0:
                break
            apns = batch[["apn"]].copy()
            x_batch = _feature_fn(batch)
            y_batch = model_obj.predict(x_batch)
            yield batch, apns, y_batch, x_batch
            offset += batch_size

    # --- 4. Feature matrix builder ------------------------------------------
    def _feature_fn(df: pd.DataFrame) -> pd.DataFrame:
        """Build the feature matrix the cached model was fitted on.

        Every column in ``expected_cols`` is present: the query selects the
        numeric features and the ResNet PCA components, and the one-hot block
        is zero-initialised here. ``load_latest_model`` only returns artifacts
        this builder can feed, so the final selection cannot miss a column.
        """
        df = df.copy()
        df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
        df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)

        for col in NUMERIC_FEATURES:
            if col in df.columns:
                df[col] = df[col].astype(np.float32)

        # One-hot columns: zero-initialise every trained category, then set the
        # ones this parcel belongs to; categories absent here stay zero.
        for col in expected_cols:
            if col.startswith(LDC_PREFIX):
                df[col] = 0

        ldc_series = df["land_development_category"]
        for cat in ldc_series.unique():
            col = f"{LDC_PREFIX}{cat}"
            if col in df.columns:
                df[col] = (ldc_series == cat).astype(int)

        return df[expected_cols]

    # --- 5. Run inference ---------------------------------------------------
    results_parts: list[pd.DataFrame] = []
    for batch, apns, y_batch, x_batch in _stream_region_data(context):
        partial = apns
        # The model predicts dwelling units per square foot of Overture building
        # area; scale by that observed area to get dwelling units.
        for i, target in enumerate(DU_TARGETS):
            partial[target] = np.round(
                np.maximum(y_batch[:, i], 0.0) * batch[DU_RATIO_DENOMINATOR]
            ).astype(np.float32)
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    results["du_total"] = results[DU_TARGETS].sum(axis=1).astype(np.float32)
    logger.info("DU regressor (%s): %d parcels predicted", region, len(results))

    # --- 6. Yield with batch-size protection --------------------------------
    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
