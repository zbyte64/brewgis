"""Tests for the trip distribution gravity model (T2).

The pure function is shared with the SQLMesh Python model, which calls it with
the scenario's parcel centroids and end-state employment/units; these tests pin
its invariants (trip conservation, non-negativity, degenerate origins) without a
database — which is also why the math lives in
``sqlmesh/models/python/_gravity_model.py`` rather than in the blueprinted model
module that imports it.

(The dbt-era file also carried six tests that recomputed the impedance and
attractiveness formulas inline and compared them to themselves — they never
called ``_gravity_model`` and could not fail for any change to it. The
invariants they were documenting are covered here through the real function.)
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume
from hypothesis import given
from hypothesis import strategies as st

from brewgis.sqlmesh.models.python._network_zones import zone_distance_matrix
from brewgis.sqlmesh.models.python._network_zones import zone_indices
from brewgis.workspace.analysis.transport import _gravity_model


class TestGravityModel:
    """Pure Python tests for gravity model math."""

    def test_simple_two_parcel_gravity(self) -> None:
        """Verify gravity model with two parcels and simple inputs."""
        trips = np.array([100.0, 200.0])
        emp = np.array([50.0, 100.0])
        du = np.array([200.0, 100.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
        assert it[0] == 0.0  # Zero self-distance = zero internal
        assert np.all(tb >= 0)
        assert np.all(ib >= 0)

    def test_total_trips_conserved(self) -> None:
        """Sum of outbound trips should not exceed total trip origins."""
        trips = np.array([100.0, 200.0, 150.0])
        xs = np.array([0.0, 3.0, 8.0])
        ys = np.array([0.0, 0.0, 0.0])
        emp = np.array([50.0, 75.0, 25.0])
        du = np.array([100.0, 200.0, 150.0])
        tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)

        for i in range(3):
            total_i = it[i] + tb[i]
            assert abs(total_i - trips[i]) < 0.001, (
                f"Origin {i}: {total_i} != {trips[i]}"
            )

    def test_avg_trip_length(self) -> None:
        """Average trip length should be distance-weighted."""
        trips = np.array([100.0, 0.0])
        emp = np.array([50.0, 50.0])
        du = np.array([100.0, 100.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
        assert al[0] >= 0
        assert al[1] == 0.0  # No outbound = zero avg length

    def test_unattractive_origin_keeps_its_trips_internal(self) -> None:
        """A parcel with no attractive destination keeps its trips internal.

        This is the branch the left join into the end state produces for a parcel
        the end state has no row for: zero employment and zero units leave the
        denominator at zero, and dropping those trips would break conservation.
        """
        trips = np.array([100.0, 0.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        emp = np.array([0.0, 0.0])
        du = np.array([0.0, 0.0])
        tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
        assert it[0] == 100.0
        assert tb[0] == 0.0
        assert al[0] == 0.0


# ════════════════════════════════════════════════════════════════
#  Property-based tests for gravity model invariants
# ════════════════════════════════════════════════════════════════
#
# Invariants verified:
#   - Non-negativity: all output columns >= 0
#   - Trip conservation: sum(outbound + internal) ≈ sum(trips)
#   - Inbound = Outbound (closed system)
#   - Internal trips ≈ 0 when attractors exist and parcels distinct
#   - Empty input returns empty output
# ────────────────────────────────────────────────────────────


# ── Hypothesis strategies ──────────────────────────────────

_ARRAY_2_5 = st.integers(min_value=2, max_value=5)

_GRAVITY_ARRAYS = _ARRAY_2_5.flatmap(
    lambda n: st.tuples(
        st.lists(
            st.floats(
                min_value=0, max_value=5000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),
        st.lists(
            st.floats(
                min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),
        st.lists(
            st.floats(
                min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),
        st.lists(
            st.floats(
                min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),
        st.lists(
            st.floats(
                min_value=0, max_value=10_000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),
    )
)


# ── Hypothesis property-based tests ─────────────────────────


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_non_negative(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """All output arrays must be non-negative."""
    trips, xs, ys, emp, du = arrays
    tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
    assert np.all(tb >= -1e-10), f"trips_outbound has negatives: {tb}"
    assert np.all(ib >= -1e-10), f"trips_inbound has negatives: {ib}"
    assert np.all(it >= -1e-10), f"trips_internal has negatives: {it}"
    assert np.all(al >= -1e-10), f"avg_trip_length has negatives: {al}"


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_trip_conservation(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Sum of outbound + internal trips must equal sum of origin trips."""
    trips, xs, ys, emp, du = arrays
    assume(np.sum(trips) > 0)
    tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
    total_out = np.sum(tb)
    total_internal = np.sum(it)
    total_origin = np.sum(trips)
    assert abs(total_out + total_internal - total_origin) < 1e-6, (
        f"Trip conservation: out={total_out:.4f} + internal={total_internal:.4f}"
        f" = {total_out + total_internal:.4f} != origin={total_origin:.4f}"
    )


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_inbound_vs_outbound(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Sum of outbound trips must equal sum of inbound trips (closed system)."""
    trips, xs, ys, emp, du = arrays
    assume(np.sum(trips) > 0)
    tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
    assert abs(np.sum(tb) - np.sum(ib)) < 1e-6, (
        f"Sum outbound={np.sum(tb):.4f} != sum inbound={np.sum(ib):.4f}"
    )


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_internal_zero_when_attractors_exist(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Internal trips should be ~0 when every origin has a destination.

    Self-distance d=0 gives impedance=0, so no trips stay internal as long as
    the attractiveness-weighted denominator is positive. The precondition is
    recomputed exactly as the model computes it rather than approximated from
    "an attractive parcel exists at non-zero distance": a subnormal
    attractiveness (5e-324 is drawable) underflows that weighted sum to zero,
    which legitimately sends the origin down the degenerate branch.
    """
    trips, xs, ys, emp, du = arrays
    assume(np.sum(trips) > 0)

    dist_matrix = np.sqrt(
        (xs[:, np.newaxis] - xs[np.newaxis, :]) ** 2
        + (ys[:, np.newaxis] - ys[np.newaxis, :]) ** 2
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        safe_dist = np.where(dist_matrix > 1e-10, dist_matrix, 0.0)
        impedance = np.where(safe_dist > 0, safe_dist ** (-2.0), 0.0)
    attract = np.maximum(emp + 0.5 * du, 0.0)
    denom = np.sum(attract[np.newaxis, :] * impedance, axis=1)
    assume(np.all(denom[trips > 0] > 0))

    tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
    assert np.all(it < 1e-10), f"Internal trips should be ~0, got max {np.max(it)}"


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_batching_matches_one_batch(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Distributing origins in batches must not change the result.

    The model bounds memory by processing origins in batches (the matrix is
    O(N^2)), which introduces exactly the per-batch bookkeeping that can go
    wrong: the self-flow diagonal and the degenerate-origin branch are both
    accumulated across batches, and the last batch is usually short.
    """
    trips, xs, ys, emp, du = arrays
    one_batch = _gravity_model(trips, xs, ys, emp, du)
    many_batches = _gravity_model(trips, xs, ys, emp, du, batch_elements=2)
    for expected, got in zip(one_batch, many_batches, strict=True):
        np.testing.assert_array_equal(expected, got)


def _test_zones(xs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Zone parcels into 20 km x-bands, with a finite, asymmetric zone matrix."""
    _, zones = np.unique(np.floor(xs / 20_000), return_inverse=True)
    zones = zones.reshape(-1).astype(np.int64)
    codes = np.arange(zones.max() + 1, dtype=float)
    matrix = np.abs(np.subtract.outer(codes, codes)) * 30_000.0 + codes[:, np.newaxis]
    return zones, matrix


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_unrouted_zones_match_euclidean(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Zone pairs the network does not connect keep the Euclidean distance."""
    trips, xs, ys, emp, du = arrays
    zones, matrix = _test_zones(xs)
    euclidean = _gravity_model(trips, xs, ys, emp, du)
    unrouted = _gravity_model(
        trips,
        xs,
        ys,
        emp,
        du,
        zones=zones,
        zone_distance_km=np.full_like(matrix, np.nan),
    )
    for expected, got in zip(euclidean, unrouted, strict=True):
        np.testing.assert_array_equal(expected, got)


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_zone_batching_matches_one_batch(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Batching must not change the network-distance result either."""
    trips, xs, ys, emp, du = arrays
    zones, matrix = _test_zones(xs)
    one_batch = _gravity_model(
        trips, xs, ys, emp, du, zones=zones, zone_distance_km=matrix
    )
    many_batches = _gravity_model(
        trips, xs, ys, emp, du, batch_elements=2, zones=zones, zone_distance_km=matrix
    )
    for expected, got in zip(one_batch, many_batches, strict=True):
        np.testing.assert_array_equal(expected, got)


class TestNetworkDistance:
    """Road-network zone distances in the gravity model."""

    def test_longer_network_path_shifts_trips_and_lengthens_them(self) -> None:
        """A 5 km road path for a 1 km pair moves trips away from it."""
        trips = np.array([100.0, 0.0, 0.0])
        xs = np.array([0.0, 1.0, 2.0])
        ys = np.zeros(3)
        emp = np.array([10.0, 10.0, 10.0])
        du = np.zeros(3)
        zones = np.arange(3, dtype=np.int64)
        matrix = np.full((3, 3), np.nan)
        matrix[0, 1] = 5.0

        euclidean = _gravity_model(trips, xs, ys, emp, du)
        # Only parcel 0 generates trips, so inbound[j] is exactly the flow 0 -> j.
        network = _gravity_model(
            trips, xs, ys, emp, du, zones=zones, zone_distance_km=matrix
        )
        _, inbound_e, _, length_e = euclidean
        _, inbound_n, _, length_n = network
        assert inbound_n[1] < inbound_e[1]
        assert inbound_n[2] > inbound_e[2]
        assert length_n[0] > length_e[0]

    def test_zones_without_distances_is_rejected(self) -> None:
        trips = np.array([1.0, 1.0])
        with pytest.raises(ValueError, match="given together"):
            _gravity_model(
                trips,
                trips,
                trips,
                trips,
                trips,
                zones=np.array([0, 1], dtype=np.int64),
            )

    def test_zone_matrix_ignores_unknown_zones_and_unlocated_parcels(self) -> None:
        """Pair rows outside the parcels' zones are dropped; no-geometry stays NaN."""
        parcel_ix, parcel_iy = zone_indices(
            np.array([100.0, 2500.0, np.nan]), np.array([100.0, 100.0, np.nan]), 1.0
        )
        zones, matrix = zone_distance_matrix(
            parcel_ix=parcel_ix,
            parcel_iy=parcel_iy,
            origin_ix=np.array([0, 1, 9]),
            origin_iy=np.array([0, 0, 9]),
            dest_ix=np.array([1, 0, 0]),
            dest_iy=np.array([0, 0, 0]),
            distance_km=np.array([3.0, 4.0, 7.0]),
        )
        z0, z1, z_nan = zones
        assert matrix[z0, z1] == 3.0
        assert matrix[z1, z0] == 4.0
        assert np.isnan(matrix[z_nan]).all()
        assert np.isnan(matrix[:, z_nan]).all()
        assert np.count_nonzero(~np.isnan(matrix)) == 2


@pytest.mark.slow
@given(_GRAVITY_ARRAYS)
def test_gravity_model_empty_input(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Empty input should return empty arrays."""
    _trips, _xs, _ys, _emp, _du = arrays
    empty = np.array([], dtype=float)
    tb, ib, it, al = _gravity_model(empty, empty, empty, empty, empty)
    assert len(tb) == 0
    assert len(ib) == 0
    assert len(it) == 0
    assert len(al) == 0
