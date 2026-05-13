"""
Mode Choice Model — T3 Module

Computes mode split for each parcel using a multinomial logit model.
Four modes: auto, transit, walk, bike.

Auto is the reference alternative (U = 0).
Transit utility includes density and transit access terms.
Walk/bike utility includes density and design (intersection density) terms.

Transit access proxy (no transit network yet):
    transit_access = 1.0 if land_dev_category IN ('urban', 'compact') else 0.0

Output:
    parcel_id, trips_auto, trips_transit, trips_walk, trips_bike,
    mode_share_auto, mode_share_transit, mode_share_walk, mode_share_bike

Materialized as: {target_schema}.mode_choice_{scenario_id}
"""

from __future__ import annotations

import deal
import numpy as np
import pandas as pd

from typing import Any
# ────────────────────────────────────────────────────────────
#  Pure logit function (shared with tests)
# ────────────────────────────────────────────────────────────


@deal.pre(
    lambda trips_outbound, ln_density, intersection_density, transit_access: (
        len(trips_outbound)
        == len(ln_density)
        == len(intersection_density)
        == len(transit_access)
    )
)
@deal.post(lambda result: len(result) == 8)
@deal.post(
    lambda result: (
        len(result[0]) == 0
        or np.all(result[4] + result[5] + result[6] + result[7] - 1.0 < 1e-10)
    )
)
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
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Multinomial logit mode split (pure function).

    Args:
        trips_outbound: 1-d array of outbound trips per parcel.
        ln_density: ln(density + 1) per parcel.
        intersection_density: Intersection density per parcel.
        transit_access: 1.0 if transit available, 0.0 otherwise.
        asc_transit: Alternative-specific constant for transit.
        asc_walk: ASC for walk.
        asc_bike: ASC for bike.
        beta_density: Coefficient for ln(density) in utility.
        beta_design_walk: Coefficient for intersection density in walk/bike.
        beta_transit_dist: Coefficient for transit access.

    Returns:
        (trips_auto, trips_transit, trips_walk, trips_bike,
         share_auto, share_transit, share_walk, share_bike)
    """
    n = len(trips_outbound)
    if n == 0:
        empty = np.array([], dtype=float)
        return (empty, empty, empty, empty, empty, empty, empty, empty)

    # Utility functions (auto is reference, U_auto = 0)
    u_auto = np.zeros(n)
    u_transit = (
        asc_transit + beta_density * ln_density + beta_transit_dist * transit_access
    )
    u_walk = (
        asc_walk + beta_density * ln_density + beta_design_walk * intersection_density
    )
    u_bike = (
        asc_bike + beta_density * ln_density + beta_design_walk * intersection_density
    )

    # Numerically stable softmax
    u_stack = np.column_stack([u_auto, u_transit, u_walk, u_bike])
    u_max = np.max(u_stack, axis=1, keepdims=True)
    exp_u = np.exp(u_stack - u_max)
    sum_exp_u = np.sum(exp_u, axis=1, keepdims=True)
    shares = exp_u / sum_exp_u

    # Apply to outbound trips
    trips_by_mode = trips_outbound.reshape(-1, 1) * shares

    return (
        trips_by_mode[:, 0],
        trips_by_mode[:, 1],
        trips_by_mode[:, 2],
        trips_by_mode[:, 3],
        shares[:, 0],
        shares[:, 1],
        shares[:, 2],
        shares[:, 3],
    )


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Compute mode split using multinomial logit.

    Reads upstream dbt models via dbt.ref(), prepares variables,
    calls _multinomial_logit(), and builds the result DataFrame.

    Args:
        dbt: dbt Python model context.
        session: SQLAlchemy connection.

    Returns:
        pd.DataFrame with mode split columns per parcel.
    """
    # Configure materialization
    dbt.config(materialized="table")

    # Read trip distribution output
    trip_dist = dbt.ref("trip_distribution")
    df_td = trip_dist.to_df()

    if len(df_td) == 0:
        return _empty_result()

    # Read end_state for D-variables (density, land_dev_category, intersection_density)
    core = dbt.ref("core_end_state")
    df_core = core.to_df()

    # Merge trip distribution with end_state D-variables
    df = df_td.merge(
        df_core[
            [
                "parcel_id",
                "dwelling_units_total",
                "population",
                "employment_total",
                "building_sqft_total",
                "land_dev_category",
                "intersection_density",
                "gross_acres",
            ]
        ],
        on="parcel_id",
        how="left",
    ).fillna(0.0)

    if len(df) == 0:
        return _empty_result()

    # Compute density (du/acre), guard against zero acres
    density = np.where(
        df["gross_acres"].values > 0,
        df["dwelling_units_total"].values / df["gross_acres"].values,
        0.0,
    )

    # Transit access proxy: urban/compact areas have transit
    transit_access = np.where(
        df["land_dev_category"].isin(["urban", "compact"]),
        1.0,
        0.0,
    )

    # Log-transformed density: ln(density + 1) to handle zero density
    ln_density = np.log(density + 1.0)

    # Delegate to pure function
    (
        ta,
        tt,
        tw,
        tb,
        sa,
        st_,
        sw,
        sb,
    ) = _multinomial_logit(
        trips_outbound=df["trips_outbound"].values,
        ln_density=ln_density,
        intersection_density=df["intersection_density"].values,
        transit_access=transit_access,
    )

    # Build result DataFrame
    result_df = pd.DataFrame(
        {
            "parcel_id": df["parcel_id"].values,
            "trips_auto": ta,
            "trips_transit": tt,
            "trips_walk": tw,
            "trips_bike": tb,
            "mode_share_auto": sa,
            "mode_share_transit": st_,
            "mode_share_walk": sw,
            "mode_share_bike": sb,
        }
    )

    return result_df


def _empty_result() -> pd.DataFrame:
    """Return an empty DataFrame with the expected schema."""
    return pd.DataFrame(
        columns=[
            "parcel_id",
            "trips_auto",
            "trips_transit",
            "trips_walk",
            "trips_bike",
            "mode_share_auto",
            "mode_share_transit",
            "mode_share_walk",
            "mode_share_bike",
        ]
    )
