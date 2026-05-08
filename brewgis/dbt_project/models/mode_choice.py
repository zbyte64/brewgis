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

import numpy as np
import pandas as pd


def model(dbt, session):
    """Compute mode split using multinomial logit.

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

    # Logit parameters (defaults from plan)
    # Auto is the reference alternative (U_auto = 0)
    asc_transit = -2.0
    asc_walk = -1.5
    asc_bike = -2.5
    # Density coefficient: positive means density increases utility of
    # non-auto modes (Ewing & Cervero 2010: density reduces VMT).
    beta_density = 0.15
    beta_design_walk = 0.05
    beta_transit_dist = 0.02

    # Compute density (du/acre), guard against zero acres
    df["density"] = np.where(
        df["gross_acres"] > 0,
        df["dwelling_units_total"] / df["gross_acres"],
        0.0,
    )

    # Transit access proxy: urban/compact areas have transit
    df["transit_access"] = np.where(
        df["land_dev_category"].isin(["urban", "compact"]),
        1.0,
        0.0,
    )

    # Compute log-transformed density for utility functions
    # ln(density + 1) to handle zero density
    ln_density = np.log(df["density"].values + 1.0)

    # Utility functions
    # U_auto = 0 (reference)
    u_auto = np.zeros(len(df))

    u_transit = (
        asc_transit
        + beta_density * ln_density
        + beta_transit_dist * df["transit_access"].values
    )

    u_walk = (
        asc_walk
        + beta_density * ln_density
        + beta_design_walk * df["intersection_density"].values
    )

    u_bike = (
        asc_bike
        + beta_density * ln_density
        + beta_design_walk * df["intersection_density"].values
    )

    # Logit: P(mode) = exp(U_mode) / sum(exp(U_all))
    u_stack = np.column_stack([u_auto, u_transit, u_walk, u_bike])

    # Numerically stable softmax: subtract max per row before exp
    u_max = np.max(u_stack, axis=1, keepdims=True)
    exp_u = np.exp(u_stack - u_max)
    sum_exp_u = np.sum(exp_u, axis=1, keepdims=True)
    mode_shares = exp_u / sum_exp_u

    # Apply shares to outbound trips
    trips_outbound = df["trips_outbound"].values.reshape(-1, 1)
    trips_by_mode = trips_outbound * mode_shares

    # Build result DataFrame
    result_df = pd.DataFrame(
        {
            "parcel_id": df["parcel_id"].values,
            "trips_auto": trips_by_mode[:, 0],
            "trips_transit": trips_by_mode[:, 1],
            "trips_walk": trips_by_mode[:, 2],
            "trips_bike": trips_by_mode[:, 3],
            "mode_share_auto": mode_shares[:, 0],
            "mode_share_transit": mode_shares[:, 1],
            "mode_share_walk": mode_shares[:, 2],
            "mode_share_bike": mode_shares[:, 3],
        }
    )

    return result_df


def _empty_result():
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
