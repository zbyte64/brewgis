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

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Origins are processed in batches to bound memory.
# Each batch allocates BATCH_SIZE x N float32 arrays.
# With 50k destinations and 2k batch: ~400 MB per temp array, ~2 GB peak.
BATCH_SIZE = 2000


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
    """Execute the gravity model trip distribution with batched origin processing.

    Reads upstream dbt models via dbt.ref(), processes origins in batches
    to bound memory, and returns a DataFrame.
    """
    dbt.config(materialized="table")

    # ── Read and merge data ──────────────────────────────────
    trip_gen = dbt.ref("trip_generation")
    df_tg = trip_gen.to_df()
    if len(df_tg) == 0:
        return _empty_result()

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

    core = dbt.ref("core_end_state")
    df_core = core.to_df()

    df = df_tg.merge(df_centroids, on="parcel_id", how="inner")
    if len(df) == 0:
        return _empty_result()
    df = df.merge(
        df_core[["parcel_id", "employment_total", "dwelling_units_total"]],
        on="parcel_id", how="left",
    ).fillna(0.0)

    parcel_ids = df["parcel_id"].values
    trips = df["trips_total"].values
    xs_vals = df["x"].values
    ys_vals = df["y"].values
    emp = df["employment_total"].values
    du = df["dwelling_units_total"].values
    n_total = len(parcel_ids)

    b = float(dbt.config.get("transport_impedance_exponent", 2.0))
    emp_weight = float(dbt.config.get("transport_attraction_employment_weight", 1.0))
    du_weight = float(dbt.config.get("transport_attraction_du_weight", 0.5))

    # ── Batched gravity model ────────────────────────────────
    attract = np.maximum(emp_weight * emp + du_weight * du, 0.0).astype(np.float32)

    logger.info(
        "Running batched gravity model on %d parcels (batch_size=%d, b=%s)",
        n_total, BATCH_SIZE, b,
    )

    outbound = np.zeros(n_total, dtype=np.float64)
    inbound = np.zeros(n_total, dtype=np.float64)
    internal = np.zeros(n_total, dtype=np.float64)
    dist_weighted = np.zeros(n_total, dtype=np.float64)

    n_batches = (n_total + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(n_batches):
        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, n_total)
        batch_slice = slice(start, end)
        b_size = end - start

        logger.info("  Batch %d/%d: origins %d-%d", batch_idx + 1, n_batches, start, end - 1)

        dx = xs_vals[batch_slice, np.newaxis] - xs_vals[np.newaxis, :]
        dy = ys_vals[batch_slice, np.newaxis] - ys_vals[np.newaxis, :]
        dist_matrix = np.sqrt(np.square(dx) + np.square(dy))

        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dist_matrix > 0, dist_matrix ** (-b), 0.0)

        attract_imped = attract[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)

        valid = denom > 0
        b_origins = np.arange(start, end)

        if np.any(valid):
            frac = np.zeros((b_size, n_total), dtype=np.float32)
            with np.errstate(divide="ignore", invalid="ignore"):
                frac[valid] = attract_imped[valid] / denom[valid, np.newaxis]

            od = trips[batch_slice, np.newaxis] * frac
            self_flows = od[np.arange(b_size), b_origins]
            batch_outbound = np.sum(od, axis=1) - self_flows
            outbound[batch_slice] = batch_outbound
            internal[batch_slice] = self_flows
            inbound += np.sum(od, axis=0)
            dist_weighted[batch_slice] = np.sum(od * dist_matrix, axis=1)

        invalid = ~valid
        if np.any(invalid):
            internal[start + np.where(invalid)[0]] = trips[batch_slice][invalid]

        del dx, dy, dist_matrix, impedance, attract_imped, od, frac, self_flows

    inbound = inbound - internal
    avg_trip_length = np.where(outbound > 0, dist_weighted / outbound, 0.0)

    # ── Build result DataFrame ───────────────────────────────
    result_df = pd.DataFrame({
        "parcel_id": parcel_ids,
        "trips_outbound": outbound,
        "trips_inbound": inbound,
        "trips_internal": internal,
        "avg_trip_length_km": avg_trip_length,
    })

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
