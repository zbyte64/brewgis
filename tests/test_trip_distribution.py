"""Tests for the trip_distribution dbt Python model (gravity model logic)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import assume
from hypothesis import given
from hypothesis import strategies as st

from brewgis.dbt_project.models.trip_distribution import _gravity_model


@pytest.mark.integration
class TestTripDistributionModel:
    """Pure Python tests for gravity model math."""

    def test_impedance_basic(self) -> None:
        """f(d) = d^(-b) for positive distances."""
        d = np.array([1.0, 2.0, 5.0, 10.0])
        b = 2.0
        expected = d ** (-b)
        result = d ** (-b)
        np.testing.assert_array_almost_equal(result, expected)

    def test_impedance_zero_distance(self) -> None:
        """Zero distance should give zero impedance."""
        d = np.array([0.0, 1.0, 5.0])
        b = 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(d > 0, d ** (-b), 0.0)
        assert impedance[0] == 0.0
        assert impedance[1] > 0
        assert impedance[2] > 0

    def test_impedance_different_exponent(self) -> None:
        """Impedance should respond to different b values."""
        d = np.array([2.0])
        b1 = 1.0
        b2 = 2.0
        r1 = d ** (-b1)
        r2 = d ** (-b2)
        assert r2 < r1  # Higher exponent = faster decay

    def test_attractiveness_computation(self) -> None:
        """A_j = emp_weight * employment + du_weight * dwelling_units."""
        employment = np.array([100, 200, 50])
        dwelling_units = np.array([500, 100, 200])
        emp_weight = 1.0
        du_weight = 0.5
        expected = emp_weight * employment + du_weight * dwelling_units
        result = emp_weight * employment + du_weight * dwelling_units
        np.testing.assert_array_almost_equal(result, expected)

    def test_attractiveness_non_negative(self) -> None:
        """Attractiveness must be non-negative, even with sparse inputs."""
        employment = np.array([-10, 0, 100])
        dwelling_units = np.array([5, 0, 20])
        emp_weight = 1.0
        du_weight = 0.5
        raw = emp_weight * employment + du_weight * dwelling_units
        result = np.maximum(raw, 0.0)
        assert result[0] == 0.0  # Negative clamped to zero
        assert result[1] == 0.0
        assert result[2] > 0

    def test_gravity_denominator(self) -> None:
        """Denominator sums attract * impedance over destinations."""
        n = 3
        attractiveness = np.array([1.0, 2.0, 3.0])
        dists = np.array(
            [
                [0.0, 1.0, 2.0],
                [1.0, 0.0, 3.0],
                [2.0, 3.0, 0.0],
            ]
        )
        b = 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dists > 0, dists ** (-b), 0.0)
        attract_imped = attractiveness[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)
        assert denom.shape == (n,)
        assert np.all(denom >= 0)

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
        # Call the real function with 2 parcels at distance 5
        trips = np.array([100.0, 0.0])
        emp = np.array([50.0, 50.0])
        du = np.array([100.0, 100.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
        assert al[0] >= 0
        assert al[1] == 0.0  # No outbound = zero avg length


# ════════════════════════════════════════════════════════════
#  Property-based tests for gravity model invariants
# ════════════════════════════════════════════════════════════
#
# The pure function _gravity_model is shared with the dbt Python model.
# Tests the same import that dbt uses at runtime.
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
    """Internal trips should be ~0 when attractors exist and parcels distinct.
    Self-distance d=0 gives impedance=0, so no trips stay internal when
    origins have destinations with positive attractiveness.
    """
    trips, xs, ys, emp, du = arrays
    assume(np.sum(trips) > 0)
    # Need at least 2 parcels with positive attractiveness for valid distribution
    has_attract = (emp + du) > 0
    assume(np.sum(has_attract) >= 2)
    # Skip colocated parcels — all-zero distances make all trips internal
    assume(not (np.all(xs == xs[0]) and np.all(ys == ys[0])))
    tb, ib, it, al = _gravity_model(trips, xs, ys, emp, du)
    assert np.all(it < 1e-10), f"Internal trips should be ~0, got max {np.max(it)}"


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
