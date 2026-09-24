"""Gravity-model trip distribution — pure math, importable without a database.

Split out of :mod:`brewgis.sqlmesh.models.python.trip_distribution` because that
module is a *blueprinted* SQLMesh model: importing it resolves the project's
scenario profiles from the database, which is exactly what a unit test of this
function must not need (see ``scenario_canvas.py`` for the same split — the
model module stays thin wiring, the logic lives where it can be imported).

The model passes a scenario's parcel centroids and end-state employment/units in;
nothing here reads the database or Django settings.
"""

from __future__ import annotations

import numpy as np

# Impedance exponent: f(d) = d^-b. Higher decays faster with distance.
_IMPEDANCE_EXPONENT = 2.0
# Attractiveness weights: A_j = emp_weight * emp_j + du_weight * du_j.
_EMP_WEIGHT = 1.0
_DU_WEIGHT = 0.5

# Distances at or below this (projected units) are treated as the same location:
# a parcel is not its own destination, so self-flows stay internal.
_MIN_DIST = 1e-10

# Origins are distributed in batches. The distance matrix is O(N^2): the demo
# regions have ~213k parcels, so building it whole would need terabytes, while a
# batch bounded to this many elements keeps every temporary at ~32 MB. Batch
# size is derived per call (this many elements divided by the parcel count), so
# a small scenario is still a single batch and results are unchanged — batching
# only decides how many rows of the matrix exist at once.
_BATCH_ELEMENTS = 4_000_000


def _gravity_model(  # noqa: PLR0913, PLR0915
    trips: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    emp: np.ndarray,
    du: np.ndarray,
    b: float = _IMPEDANCE_EXPONENT,
    emp_weight: float = _EMP_WEIGHT,
    du_weight: float = _DU_WEIGHT,
    batch_elements: int = _BATCH_ELEMENTS,
    zones: np.ndarray | None = None,
    zone_distance_km: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Gravity model trip distribution (pure function).

    ``T_ij = O_i * (A_j * f(d_ij)) / sum_k(A_k * f(d_ik))`` with
    ``f(d) = d^-b`` and ``A_j = emp_weight * emp_j + du_weight * du_j``.

    Args:
        trips: 1-d array of trip origins per parcel.
        xs: 1-d array of centroid x coordinates (projected, km).
        ys: 1-d array of centroid y coordinates (projected, km).
        emp: 1-d array of employment totals per parcel.
        du: 1-d array of dwelling units per parcel.
        b: Impedance exponent (default 2.0).
        emp_weight: Attractiveness weight for employment (default 1.0).
        du_weight: Attractiveness weight for dwelling units (default 0.5).
        batch_elements: Upper bound on the elements of one origin batch's
            distance matrix (default ``_BATCH_ELEMENTS``).
        zones: Optional 1-d int array, each parcel's dense zone code (see
            ``_network_zones.zone_distance_matrix``). Given together with
            ``zone_distance_km`` or not at all.
        zone_distance_km: Optional Z x Z road-network distance between zones
            (km), NaN where the network does not connect them. A pair of
            parcels in different, connected zones travels
            ``max(network, euclidean)`` — a road path is never shorter than the
            straight line; same-zone and unconnected pairs keep the Euclidean
            distance.

    Returns:
        (trips_outbound, trips_inbound, trips_internal, avg_trip_length_km).

    An origin with no attractive destination (``denom == 0``, which includes a
    parcel the end state has no row for: its attractiveness is zero) keeps all
    of its trips internal rather than dropping them, so the four outputs always
    conserve ``sum(trips)``.
    """
    if (zones is None) != (zone_distance_km is None):
        msg = "zones and zone_distance_km must be given together"
        raise ValueError(msg)
    if zones is not None:
        zones = np.asarray(zones, dtype=np.int64)
        zone_distance_km = np.asarray(zone_distance_km, dtype=float)

    n = len(trips)
    if n == 0:
        empty = np.array([], dtype=float)
        return (empty, empty, empty, empty)

    trips = np.asarray(trips, dtype=float)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)

    # Attractiveness, clamped non-negative. A parcel with NaN coordinates (no
    # geometry) contributes impedance 0 to every origin, and an origin whose
    # denominator falls to 0 lands in the degenerate branch below.
    attract = np.maximum(
        emp_weight * np.asarray(emp, dtype=float)
        + du_weight * np.asarray(du, dtype=float),
        0.0,
    )

    trips_outbound = np.zeros(n)
    trips_inbound = np.zeros(n)
    trips_internal = np.zeros(n)
    # Self-flows of the origins that have a denominator, accumulated so the
    # matrix diagonal can be removed from ``trips_inbound`` once at the end.
    # A degenerate origin keeps its trips *internal* without ever entering the
    # matrix (its fraction row is zero), so it must not subtract anything.
    self_flow_totals = np.zeros(n)
    dist_weighted = np.zeros(n)

    batch_size = max(1, int(batch_elements) // max(n, 1))
    for start in range(0, n, batch_size):
        stop = min(start + batch_size, n)
        rows = np.arange(stop - start)

        # Distance matrix for this batch of origins (neither parcel is its own
        # destination: f(0) = 0, so self-flows stay internal).
        dx = xs[start:stop, np.newaxis] - xs[np.newaxis, :]
        dy = ys[start:stop, np.newaxis] - ys[np.newaxis, :]
        dist = np.sqrt(dx**2 + dy**2)
        if zones is not None and zone_distance_km is not None:
            # NaN-coordinate parcels keep a NaN distance (impedance 0): np.maximum
            # propagates it, and np.where keeps it on the Euclidean branch.
            zi = zones[start:stop, np.newaxis]
            zj = zones[np.newaxis, :]
            net = zone_distance_km[zi, zj]
            dist = np.where(np.isnan(net) | (zi == zj), dist, np.maximum(net, dist))

        with np.errstate(divide="ignore", invalid="ignore"):
            safe_dist = np.where(dist > _MIN_DIST, dist, 0.0)
            impedance = np.where(safe_dist > 0, safe_dist ** (-b), 0.0)

        attract_imped = attract[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)

        valid = denom > 0
        if np.any(valid):
            with np.errstate(divide="ignore", invalid="ignore"):
                frac = np.zeros_like(attract_imped)
                frac[valid] = attract_imped[valid] / denom[valid, np.newaxis]
                od = trips[start:stop, np.newaxis] * frac
                self_flows = od[rows, np.arange(start, stop)]

            trips_outbound[start:stop] = np.sum(od, axis=1) - self_flows
            trips_internal[start:stop] = self_flows
            self_flow_totals[start:stop] = self_flows
            # Column sums accumulate across batches; the diagonal is removed
            # once, after every batch has contributed.
            trips_inbound += np.sum(od, axis=0)
            dist_weighted[start:stop] = np.sum(od * dist, axis=1)

        # Origins with no attractive destination: their trips stay internal.
        invalid = np.nonzero(~valid)[0]
        if len(invalid) > 0:
            trips_internal[start + invalid] = trips[start:stop][invalid]

    trips_inbound -= self_flow_totals
    avg_trip_length = np.zeros(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        np.divide(
            dist_weighted, trips_outbound, out=avg_trip_length, where=trips_outbound > 0
        )

    return trips_outbound, trips_inbound, trips_internal, avg_trip_length
