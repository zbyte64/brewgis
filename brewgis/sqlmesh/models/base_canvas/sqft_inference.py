"""Shared LightGBM SQFT Regressor — inference-only Python SQLMesh FULL model (blueprinted).

Loads the most recently trained SACOG LightGBM multi-output regressor from the
filesystem cache and predicts per-parcel building square footage by type.

- SACOG: training (``brewgis.assessor.parcel_sqft_regressor``) runs first in
  the same plan via the conditional dependency, so the cache is always fresh.
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

from brewgis.sqlmesh.macros.region_blueprints import REGIONS
from brewgis.sqlmesh.models.python._cache import load_latest_model
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import NUMERIC_FEATURES
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import SQFT_TARGETS
from brewgis.sqlmesh.models.python.parcel_sqft_regressor import _encode_one_hots

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike


def _load_model():
    """Load the most recent trained LightGBM SQFT model from cache.

    Only ``sqft__*.pkl`` files are considered, so this regressor can never
    load another model type (du/emp_ratios) by accident.

    Returns the fitted model and its ordered target columns. Raises
    RuntimeError if no SQFT model is found or the cached targets do not
    match the expected ``SQFT_TARGETS``.
    """
    payload = load_latest_model("sqft")
    if payload is None:
        raise RuntimeError(
            "No trained LightGBM SQFT model found in planning/lightgbm_cache/. "
            "Run the SACOG pipeline (compare_sacog_basemap) first to train "
            "the SQFT regressor."
        )
    model_obj = payload["model"]
    targets = payload["targets"]
    if targets != SQFT_TARGETS:
        msg = (
            f"Loaded SQFT model has targets {targets}, expected {SQFT_TARGETS}. "
            "Retrain the SQFT regressor (remove planning/lightgbm_cache/sqft__*.pkl)."
        )
        raise RuntimeError(msg)
    return model_obj, targets


def _get_model_expected_cols(model_obj: Any) -> list[str]:
    """Extract expected feature names from the loaded LightGBM model.

    MultiOutputRegressor wraps individual LGBMRegressor instances; all share
    the same feature set.
    """
    return model_obj.estimators_[0].booster_.feature_name()


def _build_feature_matrix(
    df: pd.DataFrame,
    expected_cols: list[str],
) -> pd.DataFrame:
    """Build feature matrix matching the SACOG-trained model's expected columns.

    ``reindex`` ensures the
    output column order exactly matches what the model expects; any unexpected
    one-hot categories are silently zeroed.
    """
    df = df.copy()
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)

    # Derive one-hot category sets from expected column names
    ldc_cats = sorted({c[4:] for c in expected_cols if c.startswith("ldc_")}) or None

    df = _encode_one_hots(df, ldc_cats)

    # Reindex to match exactly; missing cols zero-filled
    return df.reindex(columns=expected_cols, fill_value=0.0).astype(np.float32)


_TRAIN_MODEL = {
    "sacog": "brewgis.assessor.parcel_sqft_regressor",
    "fresno": "",
}


@model(
    "brewgis.@{region}.sqft_inference",
    kind={"name": ModelKindName.FULL},
    description="LightGBM prediction of building floor area by type for parcels, from the SACOG-trained cache.",
    column_descriptions={
        "apn": "Assessor parcel number (APN) the prediction belongs to.",
        "bldg_sqft_detsf_sl": "Predicted detached single-family small-lot building floor area (sq ft).",
        "bldg_sqft_detsf_ll": "Predicted detached single-family large-lot building floor area (sq ft).",
        "bldg_sqft_attsf": "Predicted attached single-family building floor area (sq ft).",
        "bldg_sqft_mf": "Predicted multi-family building floor area (sq ft).",
        "bldg_sqft_retail_services": "Predicted retail services building floor area (sq ft).",
        "bldg_sqft_restaurant": "Predicted restaurant building floor area (sq ft).",
        "bldg_sqft_accommodation": "Predicted accommodation building floor area (sq ft).",
        "bldg_sqft_arts_entertainment": "Predicted arts and entertainment building floor area (sq ft).",
        "bldg_sqft_other_services": "Predicted other services building floor area (sq ft).",
        "bldg_sqft_office_services": "Predicted office services building floor area (sq ft).",
        "bldg_sqft_public_admin": "Predicted public administration building floor area (sq ft).",
        "bldg_sqft_education": "Predicted education building floor area (sq ft).",
        "bldg_sqft_medical_services": "Predicted medical services building floor area (sq ft).",
        "bldg_sqft_transport_warehousing": "Predicted transport and warehousing building floor area (sq ft).",
        "bldg_sqft_wholesale": "Predicted wholesale building floor area (sq ft).",
        "bldg_sqft_total": "Predicted total building floor area summed across all types (sq ft).",
    },
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
        ("not_null", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "brewgis.@{region}.parcel_dasymetric_weights",
        "@IF(@train_model != '', brewgis.assessor.parcel_sqft_regressor, brewgis.@{region}.parcel_shim)",
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
    """Load the SACOG-trained model and predict building sqft for the region."""
    logger = logging.getLogger(__name__)
    region = context.blueprint_var("region")

    model_obj, sqft_targets = _load_model()
    expected_cols = _get_model_expected_cols(model_obj)
    logger.info(
        "%s SQFT: loaded model with %d expected features and %d targets",
        region,
        len(expected_cols),
        len(sqft_targets),
    )

    dw_table = context.resolve_table(f"brewgis.{region}.parcel_dasymetric_weights")

    pc_cols_sql = ", ".join(f"COALESCE({c}, 0.0) AS {c}" for c in _RESNET_PC_COLS)

    query = f"""
        SELECT
            dw.apn,
            COALESCE(dw.land_development_category, '')
                AS land_development_category,
            COALESCE(dw.lot_size_acres, 0)::double precision
                AS lot_size_acres,
            COALESCE(dw.highway_intersection_density, 0)::double precision
                AS highway_intersection_density,
            COALESCE(dw.path_intersection_density, 0)::double precision
                AS path_intersection_density,
            COALESCE(dw.intersection_density, 0)::double precision
                AS intersection_density,
            COALESCE(dw.footprint_ratio, 0)::double precision
                AS footprint_ratio,
            COALESCE(dw.building_count, 0)::integer AS building_count,
            COALESCE(dw.max_levels, 1)::integer AS max_levels,
            COALESCE(dw.total_footprint_sqft, 0)::double precision
                AS total_footprint_sqft,
            {pc_cols_sql}
        FROM {dw_table} dw
        ORDER BY dw.apn
    """

    def _stream_region_data(
        ctx: ExecutionContext,
        batch_size: int = 50000,
    ):
        """Yield region inference feature batches from the dasymetric weights."""
        offset = 0
        while True:
            batch = ctx.fetchdf(f"{query} LIMIT {batch_size} OFFSET {offset}")
            if len(batch) == 0:
                break
            apns = batch[["apn"]].copy()
            x_batch = _build_feature_matrix(batch, expected_cols)
            y_batch = model_obj.predict(x_batch)
            yield batch, apns, y_batch, x_batch
            offset += batch_size

    results_parts: list[pd.DataFrame] = []
    for batch, apns, y_batch, x_batch in _stream_region_data(context):
        # TODO y_batch should apply mutually exclusive subcategory rules (ie military & public is exclusive)
        # output is predicted ratios, needs to be scaled by predict sqft of building
        # CONSIDER: we may want to softmax the outputs (all should sum to 1)
        partial = apns
        for i, target in enumerate(sqft_targets):
            partial[target] = (
                np.maximum(y_batch[:, i], 0.0).astype(np.float32)
                * batch["total_footprint_sqft"]
            )
        results_parts.append(partial)

    results = pd.concat(results_parts, ignore_index=True)
    results["bldg_sqft_total"] = results[sqft_targets].sum(axis=1).astype(np.float32)
    logger.info("SQFT regressor (%s): %d parcels predicted", region, len(results))

    _original = PostgresEngineAdapter.DEFAULT_BATCH_SIZE
    PostgresEngineAdapter.DEFAULT_BATCH_SIZE = 50000
    try:
        yield results
    finally:
        PostgresEngineAdapter.DEFAULT_BATCH_SIZE = _original
