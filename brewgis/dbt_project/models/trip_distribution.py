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

# ────────────────────────────────────────────────────────────
#  Pure gravity model function (shared with tests)
# ────────────────────────────────────────────────────────────


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
    """Gravity model trip distribution (pure function).

    Args:
        trips: 1-d array of trip origins per parcel.
        xs: 1-d array of centroid x coordinates.
        ys: 1-d array of centroid y coordinates.
        emp: 1-d array of employment totals per parcel.
        du: 1-d array of dwelling units per parcel.
        b: Impedance exponent (default 2.0).
        emp_weight: Attractiveness weight for employment (default 1.0).
        du_weight: Attractiveness weight for dwelling units (default 0.5).

    Returns:
        (trips_outbound, trips_inbound, trips_internal, avg_trip_length)
    """
    n = len(trips)
    if n == 0:
        return (
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
            np.array([], dtype=float),
        )

    # Distance matrix
    dx = xs[:, np.newaxis] - xs[np.newaxis, :]
    dy = ys[:, np.newaxis] - ys[np.newaxis, :]
    dist_matrix = np.sqrt(dx**2 + dy**2)

    # Impedance: f(d) = d^(-b)
    with np.errstate(divide="ignore", invalid="ignore"):
        impedance = np.where(dist_matrix > 0, dist_matrix ** (-b), 0.0)

    # Attractiveness (clamped to non-negative)
    attract = emp_weight * emp + du_weight * du
    attract = np.maximum(attract, 0.0)

    # Gravity model
    attract_imped = attract[np.newaxis, :] * impedance
    denom = np.sum(attract_imped, axis=1)

    # Handle per-parcel degenerate case: some origins have zero denominator
    # (no attractive destinations). Those trips stay as internal.
    trips_outbound = np.zeros(n)
    trips_inbound = np.zeros(n)
    trips_internal = np.zeros(n)
    avg_trip_length = np.zeros(n)

    # Only distribute trips for origins with non-zero denominator
    valid_origins = denom > 0
    if np.any(valid_origins):
        frac = np.zeros((n, n))
        with np.errstate(divide="ignore", invalid="ignore"):
            frac[valid_origins] = (
                attract_imped[valid_origins]
                / denom[valid_origins, np.newaxis]
            )

        od_matrix = trips[:, np.newaxis] * frac
        trips_outbound = np.sum(od_matrix, axis=1) - np.diag(od_matrix)
        trips_inbound = np.sum(od_matrix, axis=0) - np.diag(od_matrix)
        trips_internal = np.diag(od_matrix).copy()

        # Average trip length for valid origins
        with np.errstate(divide="ignore", invalid="ignore"):
            dist_weighted = np.sum(od_matrix * dist_matrix, axis=1)
            avg_trip_length = np.where(
                trips_outbound > 0, dist_weighted / trips_outbound, 0.0
            )

    # Origins with zero denominator: trips stay internal
    invalid_origins = ~valid_origins
    trips_internal[invalid_origins] = trips[invalid_origins]

    return trips_outbound, trips_inbound, trips_internal, avg_trip_length


def model(dbt, session):
    """Execute the gravity model trip distribution.

    Reads upstream dbt models via dbt.ref(), calls _gravity_model(),
    and returns a DataFrame.

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
    emp = df["employment_total"].values
    du = df["dwelling_units_total"].values

    # Get dbt vars for impedance and attraction weights
    b = float(dbt.config.get("transport_impedance_exponent", 2.0))
    emp_weight = float(dbt.config.get("transport_attraction_employment_weight", 1.0))
    du_weight = float(dbt.config.get("transport_attraction_du_weight", 0.5))

    # Delegate to pure function
    trips_outbound, trips_inbound, trips_internal, avg_trip_length = _gravity_model(
        trips, xs, ys, emp, du, b=b, emp_weight=emp_weight, du_weight=du_weight,
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
