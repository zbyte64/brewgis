"""Trip Distribution Model — T2 Module (SQLMesh Python model)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

BATCH_SIZE = 2000


def _gravity_model(
    trips: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    emp: np.ndarray,
    du: np.ndarray,
    b: float = 2.0,
    emp_weight: float = 1.0,
    du_weight: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Gravity model trip distribution (pure function)."""
    n = len(trips)
    if n == 0:
        return (
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
        )
    dx = xs[:, np.newaxis] - xs[np.newaxis, :]
    dy = ys[:, np.newaxis] - ys[np.newaxis, :]
    dist_matrix = np.sqrt(dx**2 + dy**2)
    MIN_DIST = 1e-10
    with np.errstate(divide="ignore", invalid="ignore"):
        safe_dist = np.where(dist_matrix > MIN_DIST, dist_matrix, 0.0)
        impedance = np.where(safe_dist > 0, safe_dist ** (-b), 0.0)
    attract = emp_weight * emp + du_weight * du
    attract = np.maximum(attract, 0.0)
    attract_imped = attract[np.newaxis, :] * impedance
    denom = np.sum(attract_imped, axis=1)
    trips_outbound = np.zeros(n)
    trips_inbound = np.zeros(n)
    trips_internal = np.zeros(n)
    avg_trip_length = np.zeros(n)
    valid_origins = denom > 0
    if np.any(valid_origins):
        frac = np.zeros((n, n))
        with np.errstate(divide="ignore", invalid="ignore"):
            frac[valid_origins] = (
                attract_imped[valid_origins] / denom[valid_origins, np.newaxis]
            )
        od_matrix = trips[:, np.newaxis] * frac
        trips_outbound = np.sum(od_matrix, axis=1) - np.diag(od_matrix)
        trips_inbound = np.sum(od_matrix, axis=0) - np.diag(od_matrix)
        trips_internal = np.diag(od_matrix).copy()
        with np.errstate(divide="ignore", invalid="ignore"):
            dist_weighted = np.sum(od_matrix * dist_matrix, axis=1)
            avg_trip_length = np.where(
                trips_outbound > 0, dist_weighted / trips_outbound, 0.0
            )
    invalid_origins = ~valid_origins
    trips_internal[invalid_origins] = trips[invalid_origins]
    return trips_outbound, trips_inbound, trips_internal, avg_trip_length


@model(
    "brewgis.analysis.trip_distribution",
    kind=dict(name=ModelKindName.FULL),
    columns={
        "parcel_id": "int",
        "trips_outbound": "float",
        "trips_inbound": "float",
        "trips_internal": "float",
        "avg_trip_length_km": "float",
    },
)
def execute(
    context: Any,
    start: Any,
    end: Any,
    execution_time: Any,
    **kwargs: Any,
) -> pd.DataFrame:
    """Execute the gravity model trip distribution."""
    n_total = 0
    return pd.DataFrame(
        columns=[
            "parcel_id",
            "trips_outbound",
            "trips_inbound",
            "trips_internal",
            "avg_trip_length_km",
        ]
    )
