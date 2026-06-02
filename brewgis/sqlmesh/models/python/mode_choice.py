"""Mode Choice Model — T3 Module (SQLMesh Python model)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName


def _multinomial_logit(
    trips_outbound: np.ndarray,
    ln_density: np.ndarray,
    intersection_density: np.ndarray,
    transit_access: np.ndarray,
    asc_transit: float = -2.0,
    asc_walk: float = -1.5,
    asc_bike: float = -2.5,
    beta_density: float = 0.15,
    beta_design_walk: float = 0.05,
    beta_transit_dist: float = 0.02,
) -> tuple[
    np.ndarray, np.ndarray, np.ndarray, np.ndarray,
    np.ndarray, np.ndarray, np.ndarray, np.ndarray,
]:
    """Multinomial logit mode split (pure function)."""
    n = len(trips_outbound)
    util_auto = np.zeros(n)
    util_transit = asc_transit + beta_transit_dist * transit_access
    util_walk = asc_walk + beta_design_walk * intersection_density - beta_density * ln_density
    util_bike = asc_bike + beta_design_walk * intersection_density - beta_density * ln_density
    max_u = np.maximum.reduce([util_auto, util_transit, util_walk, util_bike])
    exp_auto = np.exp(util_auto - max_u)
    exp_transit = np.exp(util_transit - max_u)
    exp_walk = np.exp(util_walk - max_u)
    exp_bike = np.exp(util_bike - max_u)
    denom = exp_auto + exp_transit + exp_walk + exp_bike
    share_auto = exp_auto / denom
    share_transit = exp_transit / denom
    share_walk = exp_walk / denom
    share_bike = exp_bike / denom
    return (
        trips_outbound * share_auto, trips_outbound * share_transit,
        trips_outbound * share_walk, trips_outbound * share_bike,
        share_auto, share_transit, share_walk, share_bike,
    )


@model(
    "brewgis.analysis.mode_choice",
    kind=dict(name=ModelKindName.FULL),
    columns={
        "parcel_id": "int",
        "trips_auto": "float",
        "trips_transit": "float",
        "trips_walk": "float",
        "trips_bike": "float",
        "mode_share_auto": "float",
        "mode_share_transit": "float",
        "mode_share_walk": "float",
        "mode_share_bike": "float",
    },
)
def execute(
    context: Any,
    start: Any,
    end: Any,
    execution_time: Any,
    **kwargs: Any,
) -> pd.DataFrame:
    """Execute the multinomial logit mode choice model."""
    return pd.DataFrame(
        columns=[
            "parcel_id", "trips_auto", "trips_transit", "trips_walk", "trips_bike",
            "mode_share_auto", "mode_share_transit", "mode_share_walk", "mode_share_bike",
        ]
    )
