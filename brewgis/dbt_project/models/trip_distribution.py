"""
Trip Distribution Model — T2 Module

Computes parcel-to-parcel trip distribution using a gravity model.
Each parcel acts as its own zone (N×N OD matrix, sparse).

Impedance: f(d) = d^(-b) where b = impedance exponent (default 2.0).
Attractiveness: A_j = employment_total + attraction_du_weight * dwelling_units_total

Algorithm:
    T_ij = O_i * (A_j * f(d_ij)) / sum_k(A_k * f(d_ik))

Output:
    parcel_id, trips_outbound, trips_inbound, trips_internal, avg_trip_length_km

Materialized as: {target_schema}.trip_distribution_{scenario_id}
"""

import numpy as np
import pandas as pd


def model(dbt, session):
    """Execute the gravity model trip distribution.

    Args:
        dbt: dbt Python model context (provides ref, config, this).
        session: SQLAlchemy connection.

    Returns:
        pd.DataFrame with columns:
            parcel_id, trips_outbound, trips_inbound,
            trips_internal, avg_trip_length_km
    """
    # Configure materialization
    dbt.config(materialized="table")

    # Read trip generation output
    trip_gen = dbt.ref("trip_generation")
    df_tg = trip_gen.to_df()

    if len(df_tg) == 0:
        return _empty_result()

    # Get centroid coordinates from the trip_generation view via PostGIS
    # dbt.ref() returns a Relation object — its string form is fully qualified
    trip_gen_ref = str(trip_gen)
    centroid_query = f"""
        SELECT
            parcel_id,
            ST_X(ST_Centroid(geom)) AS x,
            ST_Y(ST_Centroid(geom)) AS y
        FROM {trip_gen_ref}
        WHERE geom IS NOT NULL
    """
    df_centroids = pd.read_sql(centroid_query, session.connection())

    if len(df_centroids) == 0:
        return _empty_result()

    # Read end_state for attractiveness factors
    core = dbt.ref("core_end_state")
    df_core = core.to_df()

    # Merge trip generation with centroids and end_state data
    df = df_tg.merge(df_centroids, on="parcel_id", how="inner")

    if len(df) == 0:
        return _empty_result()

    df = df.merge(
        df_core[["parcel_id", "employment_total", "dwelling_units_total"]],
        on="parcel_id",
        how="left",
    ).fillna(0.0)
    parcel_ids = df["parcel_id"].values
    trips = df["trips_total"].values
    xs = df["x"].values
    ys = df["y"].values

    # Get dbt vars for impedance and attraction weights
    impedance_exponent = float(
        dbt.config.get("transport_impedance_exponent", 2.0)
    )
    attraction_emp_weight = float(
        dbt.config.get("transport_attraction_employment_weight", 1.0)
    )
    attraction_du_weight = float(
        dbt.config.get("transport_attraction_du_weight", 0.5)
    )

    # Build N×N distance matrix using broadcasting
    dx = xs[:, np.newaxis] - xs[np.newaxis, :]
    dy = ys[:, np.newaxis] - ys[np.newaxis, :]
    dist_matrix = np.sqrt(dx**2 + dy**2)

    # Impedance: f(d) = d^(-b)
    # Avoid division by zero (self-distances)
    with np.errstate(divide="ignore", invalid="ignore"):
        impedance = np.where(dist_matrix > 0, dist_matrix ** (-impedance_exponent), 0.0)

    # Attractiveness A_j
    attractiveness = (
        attraction_emp_weight * df["employment_total"].values
        + attraction_du_weight * df["dwelling_units_total"].values
    )
    attractiveness = np.maximum(attractiveness, 0.0)

    # Gravity model: T_ij = O_i * (A_j * f(d_ij)) / sum_k(A_k * f(d_ik))
    # Numerator: attract * impedance (N×N)
    attract_imped = attractiveness[np.newaxis, :] * impedance

    # Denominator: sum over destinations for each origin
    denom = np.sum(attract_imped, axis=1)

    # Avoid division by zero
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(
            denom[:, np.newaxis] > 0,
            attract_imped / denom[:, np.newaxis],
            0.0,
        )

    # Apply trip origins
    od_matrix = trips[:, np.newaxis] * frac

    # Compute outputs per parcel
    trips_outbound = np.sum(od_matrix, axis=1) - np.diag(od_matrix)
    trips_inbound = np.sum(od_matrix, axis=0) - np.diag(od_matrix)
    trips_internal = np.diag(od_matrix)

    # Average trip length (km) for outbound trips
    with np.errstate(divide="ignore", invalid="ignore"):
        dist_weighted = np.sum(od_matrix * dist_matrix, axis=1)
        avg_trip_length = np.where(
            trips_outbound > 0, dist_weighted / trips_outbound, 0.0
        )

    # Build result DataFrame
    result_df = pd.DataFrame(
        {
            "parcel_id": parcel_ids,
            "trips_outbound": trips_outbound,
            "trips_inbound": trips_inbound,
            "trips_internal": trips_internal,
            "avg_trip_length_km": avg_trip_length,
        }
    )

    return result_df


def _empty_result():
    """Return an empty DataFrame with the expected schema."""
    return pd.DataFrame(
        columns=[
            "parcel_id",
            "trips_outbound",
            "trips_inbound",
            "trips_internal",
            "avg_trip_length_km",
        ]
    )
