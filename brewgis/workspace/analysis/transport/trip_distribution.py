"""Standalone gravity model trip distribution runner.

Replicates the ``model(dbt, session)`` function from ``brewgis/dbt_project/models/trip_distribution.py``
but reads/writes Postgres directly via ``django.db.connection`` — no dbt involved.

The gravity model builds a full N-by-N origin-destination matrix. For large N
(50k+ parcels) this requires batched processing to stay within memory limits.
A batch of B origins by N destinations produces a B-by-N distance matrix;
processing one batch at a time avoids allocating the full N^2 matrix.
"""

from __future__ import annotations

import logging

import numpy as np
from django.db import connection

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = (
    "parcel_id",
    "trips_outbound",
    "trips_inbound",
    "trips_internal",
    "avg_trip_length_km",
)

# Origins are processed in batches of this size to bound memory.
# Each batch allocates BATCH_SIZE x N float32 arrays for distance,
# impedance, and OD matrices. With 50k destinations and 2k batch:
#   ~400 MB per temporary array, ~2 GB peak total.
BATCH_SIZE = 2000


def run_trip_distribution(  # noqa: PLR0913,PLR0915
    schema: str,
    scenario_id: str,
    *,
    impedance_exponent: float = 2.0,
    emp_weight: float = 1.0,
    du_weight: float = 0.5,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Run gravity model trip distribution with batched origin processing.

    Reads: ``{schema}.trip_generation_{scenario_id}`` (trips + geometry)
    Writes: ``{schema}.trip_distribution_{scenario_id}``

    Args:
        schema: Database schema name (e.g. ``sacog_demo``).
        scenario_id: Scenario identifier (e.g. ``base``).
        impedance_exponent: ``b`` parameter for ``f(d) = d^(-b)`` (default 2.0).
        emp_weight: Attractiveness weight for employment (default 1.0).
        du_weight: Attractiveness weight for dwelling units (default 0.5).
        batch_size: Origins per batch (default 2000; reduce if OOM).

    Returns:
        Number of rows written.
    """
    trip_gen_table = f"{schema}.trip_generation_{scenario_id}"
    end_state_table = f"{schema}.end_state_{scenario_id}"
    output_table = f"{schema}.trip_distribution_{scenario_id}"

    # -- Read input data ---------------------------------------------------
    query = f"""
        SELECT
            tg.parcel_id,
            tg.trips_total,
            ST_X(ST_Centroid(tg.geom))::double precision AS x,
            ST_Y(ST_Centroid(tg.geom))::double precision AS y,
            COALESCE(es.employment_total, 0.0)::double precision AS employment_total,
            COALESCE(es.dwelling_units_total, 0.0)::double precision AS dwelling_units_total
        FROM {trip_gen_table} tg
        LEFT JOIN {end_state_table} es ON tg.parcel_id = es.parcel_id
        WHERE tg.geom IS NOT NULL
    """  # noqa: S608 -- schema/table names from controlled constants

    with connection.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()

    if not rows:
        logger.warning("No rows returned from %s", trip_gen_table)
        _create_empty_output(schema, scenario_id)
        return 0

    # Unpack into numpy arrays (float32 to halve memory for large N)
    n_total = len(rows)
    parcel_ids = np.array([r[0] for r in rows], dtype=np.int64)
    trips = np.array([r[1] for r in rows], dtype=np.float32)
    xs = np.array([r[2] for r in rows], dtype=np.float32)
    ys = np.array([r[3] for r in rows], dtype=np.float32)
    emp = np.array([r[4] for r in rows], dtype=np.float32)
    du = np.array([r[5] for r in rows], dtype=np.float32)

    # Attractiveness (shared across all batches)
    attract = np.maximum(emp_weight * emp + du_weight * du, 0.0).astype(np.float32)

    logger.info(
        "Running gravity model on %d parcels in batches of %d "
        "(b=%s, emp_w=%s, du_w=%s)",
        n_total,
        batch_size,
        impedance_exponent,
        emp_weight,
        du_weight,
    )

    # -- Batched gravity model ---------------------------------------------
    # Full-size output accumulators (float64 to avoid precision loss on sum)
    outbound = np.zeros(n_total, dtype=np.float64)
    inbound = np.zeros(n_total, dtype=np.float64)
    internal = np.zeros(n_total, dtype=np.float64)
    dist_weighted = np.zeros(n_total, dtype=np.float64)

    n_batches = (n_total + batch_size - 1) // batch_size

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, n_total)
        batch_slice = slice(start, end)
        b_size = end - start

        logger.info(
            "  Batch %d/%d: origins %d-%d",
            batch_idx + 1,
            n_batches,
            start,
            end - 1,
        )

        # Distance matrix for this batch (B x N)
        dx = xs[batch_slice, np.newaxis] - xs[np.newaxis, :]
        dy = ys[batch_slice, np.newaxis] - ys[np.newaxis, :]
        dist_matrix = np.sqrt(np.square(dx) + np.square(dy))

        # Impedance: f(d) = d^(-b), with d = 0 => 0
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(
                dist_matrix > 0, dist_matrix ** (-impedance_exponent), 0.0
            )

        attract_imped = attract[np.newaxis, :] * impedance  # B x N
        denom = np.sum(attract_imped, axis=1)  # B

        valid = denom > 0
        b_origins = np.arange(start, end)

        if np.any(valid):
            frac = np.zeros((b_size, n_total), dtype=np.float32)
            with np.errstate(divide="ignore", invalid="ignore"):
                frac[valid] = attract_imped[valid] / denom[valid, np.newaxis]

            od = trips[batch_slice, np.newaxis] * frac  # B x N

            # Diagonal (self-flows for origins in this batch)
            self_flows = od[np.arange(b_size), b_origins]

            batch_outbound = np.sum(od, axis=1) - self_flows
            outbound[batch_slice] = batch_outbound

            internal[batch_slice] = self_flows

            # Inbound: accumulate flows into each destination from this batch
            inbound += np.sum(od, axis=0)

            # Weighted distance for avg trip length
            dist_weighted[batch_slice] = np.sum(od * dist_matrix, axis=1)

        # Origins with zero denominator: all trips stay internal
        invalid = ~valid
        if np.any(invalid):
            internal[start + np.where(invalid)[0]] = trips[batch_slice][invalid]

        # Clean up batch temporaries
        del dx, dy, dist_matrix, impedance, attract_imped, od, frac, self_flows

    # Finalize inbound: subtract self-flows (internal) from accumulated inbound
    inbound = inbound - internal

    # Average trip length (only for parcels with outbound > 0)
    avg_trip_length = np.where(outbound > 0, dist_weighted / outbound, 0.0)

    # -- Write results to Postgres -----------------------------------------
    _create_output_table(schema, scenario_id)

    data = [
        (int(pid), float(ob), float(ib), float(it), float(atl))
        for pid, ob, ib, it, atl in zip(
            parcel_ids, outbound, inbound, internal, avg_trip_length, strict=True
        )
    ]

    columns = ", ".join(OUTPUT_COLUMNS)
    placeholders = ", ".join(["%s"] * len(OUTPUT_COLUMNS))
    with connection.cursor() as cursor:
        cursor.executemany(
            f"INSERT INTO {output_table} ({columns}) VALUES ({placeholders})",  # noqa: S608
            data,
        )

    row_count = len(data)
    logger.info("Wrote %d rows to %s", row_count, output_table)
    return row_count


def _create_output_table(schema: str, scenario_id: str) -> None:
    """Create output table (truncates if exists)."""
    output_table = f"{schema}.trip_distribution_{scenario_id}"
    cols = (
        "parcel_id BIGINT PRIMARY KEY, "
        "trips_outbound DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "trips_inbound DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "trips_internal DOUBLE PRECISION NOT NULL DEFAULT 0.0, "
        "avg_trip_length_km DOUBLE PRECISION NOT NULL DEFAULT 0.0"
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {output_table} ({cols})")
        cursor.execute(f"TRUNCATE {output_table}")


def _create_empty_output(schema: str, scenario_id: str) -> None:
    """Create an empty output table when there is no input data."""
    _create_output_table(schema, scenario_id)
