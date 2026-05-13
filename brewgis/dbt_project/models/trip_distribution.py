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

import deal
import numpy as np
import pandas as pd

from typing import Any
logger = logging.getLogger(__name__)

# Origins are processed in batches to bound memory.
# Each batch allocates BATCH_SIZE x N float32 arrays.
# With 50k destinations and 2k batch: ~400 MB per temp array, ~2 GB peak.
BATCH_SIZE = 2000


# ────────────────────────────────────────────────────────────
#  Pure gravity model function (shared with tests)
# ────────────────────────────────────────────────────────────


@deal.pre(
    lambda trips, xs, ys, emp, du: (
        len(trips) == len(xs) == len(ys) == len(emp) == len(du)
    )
)
@deal.pre(lambda trips: len(trips) >= 0)
@deal.post(lambda result: all(len(r) == len(result[0]) for r in result))
@deal.post(
    lambda result: all(
        np.all(arr >= -1e-10) if len(arr) > 0 else True for arr in result
    )
)
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
    # Clamp minimum distance to prevent overflow of tiny squared reciprocals.
    MIN_DIST = 1e-10
    with np.errstate(divide="ignore", invalid="ignore"):
        safe_dist = np.where(dist_matrix > MIN_DIST, dist_matrix, 0.0)
        impedance = np.where(safe_dist > 0, safe_dist ** (-b), 0.0)

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
                attract_imped[valid_origins] / denom[valid_origins, np.newaxis]
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


def model(dbt: Any, session: Any) -> pd.DataFrame:
    """Execute the gravity model trip distribution with batched origin processing.

    Reads upstream dbt models via dbt.ref(), processes origins in batches
    to bound memory, and returns a DataFrame.

    Distance source is controlled by the ``transport_distance_source`` var:
      - ``"euclidean"`` (default): compute crow-flies distances from parcel centroids.
      - ``"network"``: read from pre-computed ``trip_distribution_inputs_{scenario_id}``
        table (produced by DistanceMatrixPreprocessor).
    """
    dbt.config(materialized="table")

    distance_source = dbt.config.get("transport_distance_source", "euclidean")
    scenario_id = dbt.config.get("scenario_id", "default")
    target_schema = dbt.config.get("target_schema", "public")

    # ── Read and merge data ──────────────────────────────────
    trip_gen = dbt.ref("trip_generation")
    df_tg = trip_gen.to_df()
    if len(df_tg) == 0:
        return _empty_result()

    core = dbt.ref("core_end_state")
    df_core = core.to_df()

    parcel_ids = df_tg["parcel_id"].values
    trips = df_tg["trips_total"].values
    n_total = len(parcel_ids)

    if n_total == 0:
        return _empty_result()

    b = float(dbt.config.get("transport_impedance_exponent", 2.0))
    emp_weight = float(dbt.config.get("transport_attraction_employment_weight", 1.0))
    du_weight = float(dbt.config.get("transport_attraction_du_weight", 0.5))

    # ── Distance source selection ────────────────────────────
    if distance_source == "network":
        logger.info(
            "Using network distances for trip distribution (scenario %s, schema %s)",
            scenario_id,
            target_schema,
        )
        result_df = _run_with_network_distances(
            dbt=dbt,
            session=session,
            parcel_ids=parcel_ids,
            trips=trips,
            b=b,
            emp_weight=emp_weight,
            du_weight=du_weight,
            scenario_id=scenario_id,
            target_schema=target_schema,
        )
    else:
        logger.info("Using Euclidean (crow-flies) distances for trip distribution")
        result_df = _run_with_euclidean_distances(
            dbt=dbt,
            session=session,
            df_tg=df_tg,
            df_core=df_core,
            parcel_ids=parcel_ids,
            trips=trips,
            n_total=n_total,
            b=b,
            emp_weight=emp_weight,
            du_weight=du_weight,
        )

    return result_df


def _run_with_euclidean_distances(
    dbt: Any,
    session: Any,
    df_tg: pd.DataFrame,
    df_core: pd.DataFrame,
    parcel_ids: np.ndarray,
    trips: np.ndarray,
    n_total: int,
    b: float,
    emp_weight: float,
    du_weight: float,
) -> pd.DataFrame:
    """Run gravity model using centroid-based Euclidean distances (original behavior)."""
    trip_gen_ref = str(dbt.ref("trip_generation"))
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

    df = df_tg.merge(df_centroids, on="parcel_id", how="inner")
    if len(df) == 0:
        return _empty_result()
    df = df.merge(
        df_core[["parcel_id", "employment_total", "dwelling_units_total"]],
        on="parcel_id",
        how="left",
    ).fillna(0.0)

    xs_vals = df["x"].values
    ys_vals = df["y"].values
    emp = df["employment_total"].values
    du = df["dwelling_units_total"].values

    attract = np.maximum(emp_weight * emp + du_weight * du, 0.0).astype(np.float32)  # type: ignore[operator]

    logger.info(
        "Running batched Euclidean gravity model on %d parcels (batch_size=%d, b=%s)",
        n_total,
        BATCH_SIZE,
        b,
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
        b_origins = np.arange(start, end)
        b_size = end - start

        logger.info(
            "  Batch %d/%d: origins %d-%d",
            batch_idx + 1,
            n_batches,
            start,
            end - 1,
        )

        dx = xs_vals[batch_slice, np.newaxis] - xs_vals[np.newaxis, :]
        dy = ys_vals[batch_slice, np.newaxis] - ys_vals[np.newaxis, :]
        dist_matrix = np.sqrt(np.square(dx) + np.square(dy))

        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dist_matrix > 0, dist_matrix ** (-b), 0.0)

        _accumulate_batch(
            b_origins=b_origins,
            b_size=b_size,
            trips=trips,
            attract=attract,
            impedance=impedance,
            dist_matrix=dist_matrix,
            start=start,
            outbound=outbound,
            inbound=inbound,
            internal=internal,
            dist_weighted=dist_weighted,
            n_total=n_total,
        )

    inbound = inbound - internal
    avg_trip_length = np.where(outbound > 0, dist_weighted / outbound, 0.0)

    return pd.DataFrame(
        {
            "parcel_id": parcel_ids,
            "trips_outbound": outbound,
            "trips_inbound": inbound,
            "trips_internal": internal,
            "avg_trip_length_km": avg_trip_length,
        }
    )


def _run_with_network_distances(
    dbt: Any,
    session: Any,
    parcel_ids: np.ndarray,
    trips: np.ndarray,
    b: float,
    emp_weight: float,
    du_weight: float,
    scenario_id: str,
    target_schema: str,
) -> pd.DataFrame:
    """Run gravity model using pre-computed network distances."""
    inputs_table = f"{target_schema}.trip_distribution_inputs_{scenario_id}"
    logger.info(
        "Reading network distance matrix from %s (%d parcels)",
        inputs_table,
        len(parcel_ids),
    )

    # Read pre-computed OD distances
    query = f"""
        SELECT origin_parcel_id, dest_parcel_id, network_distance_km
        FROM {inputs_table}
    """
    df_distances = pd.read_sql(query, session.connection())
    if len(df_distances) == 0:
        logger.warning("Distance matrix table %s is empty", inputs_table)
        return _empty_result()

    # Build an n x n distance matrix from the OD list
    pid_to_idx = {pid: i for i, pid in enumerate(parcel_ids)}
    n_total = len(parcel_ids)
    dist_matrix = np.zeros((n_total, n_total), dtype=np.float32)
    for _, row in df_distances.iterrows():
        o = pid_to_idx.get(row["origin_parcel_id"])
        d = pid_to_idx.get(row["dest_parcel_id"])
        if o is not None and d is not None:
            dist_matrix[o, d] = row["network_distance_km"]

    # Read employment/DU for attractiveness
    core = dbt.ref("core_end_state")
    df_core = core.to_df()
    df_core = df_core.set_index("parcel_id")
    df_core = df_core.reindex(parcel_ids)
    emp = df_core["employment_total"].fillna(0).values
    du = df_core["dwelling_units_total"].fillna(0).values
    attract = np.maximum(emp_weight * emp + du_weight * du, 0.0).astype(np.float32)

    logger.info(
        "Running batched network-distances gravity model on %d parcels (batch_size=%d, b=%s)",
        n_total,
        BATCH_SIZE,
        b,
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
        batch_origins = np.arange(start, end)

        logger.info(
            "  Batch %d/%d: origins %d-%d",
            batch_idx + 1,
            n_batches,
            start,
            end - 1,
        )

        batch_dists = dist_matrix[batch_slice, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(batch_dists > 0, batch_dists ** (-b), 0.0)

        _accumulate_batch(
            b_origins=batch_origins,
            b_size=b_size,
            trips=trips,
            attract=attract,
            impedance=impedance,
            dist_matrix=batch_dists,
            start=start,
            outbound=outbound,
            inbound=inbound,
            internal=internal,
            dist_weighted=dist_weighted,
            n_total=n_total,
        )

    inbound = inbound - internal
    avg_trip_length = np.where(outbound > 0, dist_weighted / outbound, 0.0)

    return pd.DataFrame(
        {
            "parcel_id": parcel_ids,
            "trips_outbound": outbound,
            "trips_inbound": inbound,
            "trips_internal": internal,
            "avg_trip_length_km": avg_trip_length,
        }
    )


@deal.pre(
    lambda b_size, start, n_total: (
        start >= 0 and b_size > 0 and start + b_size <= n_total
    )
)
@deal.pre(lambda b_origins, b_size: len(b_origins) == b_size)
def _accumulate_batch(
    b_origins: np.ndarray,
    b_size: int,
    trips: np.ndarray,
    attract: np.ndarray,
    impedance: np.ndarray,
    dist_matrix: np.ndarray,
    start: int,
    outbound: np.ndarray,
    inbound: np.ndarray,
    internal: np.ndarray,
    dist_weighted: np.ndarray,
    n_total: int,
) -> None:
    """Accumulate trip flows from one batch into the global arrays."""
    attract_imped = attract[np.newaxis, :] * impedance
    denom = np.sum(attract_imped, axis=1)
    valid = denom > 0

    if np.any(valid):
        frac = np.zeros((b_size, n_total), dtype=np.float32)
        with np.errstate(divide="ignore", invalid="ignore"):
            frac[valid] = attract_imped[valid] / denom[valid, np.newaxis]

        od = trips[start : start + b_size, np.newaxis] * frac
        self_flows = od[np.arange(b_size), b_origins]
        batch_outbound = np.sum(od, axis=1) - self_flows
        outbound[start : start + b_size] = batch_outbound
        internal[start : start + b_size] = self_flows
        inbound += np.sum(od, axis=0)
        dist_weighted[start : start + b_size] = np.sum(od * dist_matrix, axis=1)

    invalid_idx = np.where(~valid)[0]
    if len(invalid_idx) > 0:
        internal[start + invalid_idx] = trips[start : start + b_size][invalid_idx]


def _empty_result() -> pd.DataFrame:
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
