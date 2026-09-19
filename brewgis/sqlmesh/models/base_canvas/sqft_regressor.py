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

from brewgis.sqlmesh.models.python._cache import load_latest_model
from brewgis.sqlmesh.models.python._feature_cols import _RESNET_PC_COLS
from brewgis.sqlmesh.models.python._predict import predict_in_batches

if TYPE_CHECKING:
    from sqlmesh.core.context import ExecutionContext
    from sqlmesh.utils.date import TimeLike

SQFT_TARGETS = [
    "bldg_sqft_detsf_sl",
    "bldg_sqft_detsf_ll",
    "bldg_sqft_attsf",
    "bldg_sqft_mf",
    "bldg_sqft_retail_services",
    "bldg_sqft_restaurant",
    "bldg_sqft_accommodation",
    "bldg_sqft_arts_entertainment",
    "bldg_sqft_other_services",
    "bldg_sqft_office_services",
    "bldg_sqft_public_admin",
    "bldg_sqft_education",
    "bldg_sqft_medical_services",
    "bldg_sqft_transport_warehousing",
    "bldg_sqft_wholesale",
]

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


def _load_model() -> tuple[Any, list[str]]:
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


def _encode_one_hots(
    df: pd.DataFrame,
    landuse_prefixes: list[str],
    zone_prefixes: list[str],
    ldev_cats: list[str] | None = None,
) -> pd.DataFrame:
    """One-hot encode categorical features (no built_form_key encoding)."""
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


def _build_feature_matrix(
    df: pd.DataFrame,
    expected_cols: list[str],
) -> pd.DataFrame:
    """Build feature matrix matching the SACOG-trained model's expected columns.

    Regions without ``landuse``/``zone`` default to ``"XX"``/``"X"``. The
    one-hot encoder maps them to a "missing" category. ``reindex`` ensures the
    output column order exactly matches what the model expects; any unexpected
    one-hot categories are silently zeroed.
    """
    df = df.copy()
    df["landuse_prefix"] = df["landuse"].fillna("XX").str[:2]
    df["zone_prefix"] = df["zone"].fillna("X").str[:1]
    df["building_count"] = np.clip(df["building_count"], 0, 50).astype(np.int32)
    df["max_levels"] = df["max_levels"].fillna(1).astype(np.int32)
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(np.float32)

    # Derive one-hot category sets from expected column names
    lu_prefixes = sorted({c[3:] for c in expected_cols if c.startswith("lu_")})
    zone_prefixes = sorted({c[5:] for c in expected_cols if c.startswith("zone_")})
    ldc_cats = sorted({c[4:] for c in expected_cols if c.startswith("ldc_")}) or None

    df = _encode_one_hots(df, lu_prefixes, zone_prefixes, ldc_cats)

    # Reindex to match exactly; missing cols zero-filled
    return df.reindex(columns=expected_cols, fill_value=0.0).astype(np.float32)


@model(
    "brewgis.@{region}.sqft_regressor",
    kind={"name": ModelKindName.FULL},
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
    blueprints=[
        {"region": "sacog", "train_model": "brewgis.assessor.parcel_sqft_regressor"},
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
            dw.landuse AS landuse,
            dw.zone AS zone,
            COALESCE(dw.land_development_category, 'urban')
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
            COALESCE(dw.residential_building_sqft, 0)::double precision
                AS residential_building_sqft,
            COALESCE(dw.commercial_building_sqft, 0)::double precision
                AS commercial_building_sqft,
            COALESCE(dw.industrial_building_sqft, 0)::double precision
                AS industrial_building_sqft,
            COALESCE(dw.other_building_sqft, 0)::double precision
                AS other_building_sqft,
            COALESCE(dw.total_footprint_sqft, 0)::double precision
                AS total_footprint_sqft,
            {pc_cols_sql}
        FROM {dw_table} dw
        ORDER BY dw.apn
    """

    def _stream_region_data(
        ctx: ExecutionContext,
        batch_size: int = 50000,
    ) -> Iterator[pd.DataFrame]:
        """Yield region inference feature batches from the dasymetric weights."""
        offset = 0
        while True:
            batch = ctx.fetchdf(f"{query} LIMIT {batch_size} OFFSET {offset}")
            if len(batch) == 0:
                break
            yield batch
            offset += batch_size

    def _features(df: pd.DataFrame) -> pd.DataFrame:
        return _build_feature_matrix(df, expected_cols)

    results_parts: list[pd.DataFrame] = []
    for apns, y_batch in predict_in_batches(
        _stream_region_data(context),
        model_obj,
        _features,
    ):
        partial = apns
        for i, target in enumerate(sqft_targets):
            partial[target] = np.maximum(y_batch[:, i], 0.0).astype(np.float32)
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
