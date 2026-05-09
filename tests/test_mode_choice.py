"""Tests for the mode_choice dbt Python model (logit mode split logic)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck
from hypothesis import assume
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st

from brewgis.dbt_project.models.mode_choice import _multinomial_logit


@pytest.mark.integration
class TestModeChoiceLogit:
    """Pure Python tests for multinomial logit mode choice math."""

    def test_softmax_sum_to_one(self) -> None:
        """Mode shares for each parcel should sum to 1.0."""
        n = 4
        trips = np.ones(n)
        ln_dens = np.zeros(n)
        inter_dens = np.zeros(n)
        transit_acc = np.zeros(n)
        *_, sa, st_, sw, sb = _multinomial_logit(
            trips, ln_dens, inter_dens, transit_acc
        )
        row_sums = sa + st_ + sw + sb
        np.testing.assert_array_almost_equal(row_sums, np.ones(n))

    def test_auto_dominates_defaults(self) -> None:
        """With default parameters, auto should have highest share."""
        trips = np.array([100.0])
        ln_density = np.log(5.0 + 1.0)
        intersection_density = np.array([0.0])
        transit_access = np.array([0.0])
        *_, sa, st_, sw, sb = _multinomial_logit(
            trips,
            ln_density,
            intersection_density,
            transit_access,
        )
        assert sa[0] > st_[0]  # auto > transit
        assert sa[0] > sw[0]  # auto > walk
        assert sa[0] > sb[0]  # auto > bike

    def test_transit_access_increases_share(self) -> None:
        """Transit access should increase transit share."""
        trips = np.array([100.0, 100.0])
        # Urban (density=15, transit=1) vs rural (density=2, transit=0)
        ln_dens = np.log(np.array([15.0, 2.0]) + 1.0)
        inter_dens = np.zeros(2)
        transit = np.array([1.0, 0.0])
        *_, sa, st_, sw, sb = _multinomial_logit(trips, ln_dens, inter_dens, transit)
        assert st_[0] > st_[1], (
            f"Urban transit share {st_[0]:.4f} should exceed rural {st_[1]:.4f}"
        )

    def test_density_reduces_auto_share(self) -> None:
        """Higher density should reduce auto share."""
        trips = np.array([100.0, 100.0])
        ln_dense = np.log(30.0 + 1.0)
        ln_sparse = np.log(2.0 + 1.0)
        ln_dens = np.array([ln_dense, ln_sparse])
        inter_dens = np.zeros(2)
        transit = np.zeros(2)
        *_, sa, st_, sw, sb = _multinomial_logit(trips, ln_dens, inter_dens, transit)
        assert sa[0] < sa[1], (
            f"Dense auto share {sa[0]:.4f} should be less than sparse {sa[1]:.4f}"
        )

    def test_walk_share_higher_with_design(self) -> None:
        """Higher intersection density should increase walk/bike share."""
        trips = np.array([100.0, 100.0])
        ln_dens = np.log(10.0 + 1.0) * np.ones(2)
        inter_dens = np.array([10.0, 0.0])  # Urban grid vs rural
        transit = np.zeros(2)
        *_, sa, st_, sw, sb = _multinomial_logit(trips, ln_dens, inter_dens, transit)
        assert sw[0] > sw[1], (
            f"High design walk share {sw[0]:.4f} should exceed low {sw[1]:.4f}"
        )

    def test_trips_by_mode_sum_to_outbound(self) -> None:
        """Sum of trips by mode should equal trips_outbound."""
        trips_outbound = np.array([100.0, 200.0, 150.0])
        density = np.array([5.0, 15.0, 2.0])
        ln_density = np.log(density + 1.0)
        inter_dens = np.array([0.0, 5.0, 0.0])
        transit_access = np.array([0.0, 1.0, 0.0])

        ta, tt, tw, tb, *_ = _multinomial_logit(
            trips_outbound, ln_density, inter_dens, transit_access
        )
        trips_sum = ta + tt + tw + tb
        np.testing.assert_array_almost_equal(trips_sum, trips_outbound)

    def test_zero_trips_parcel(self) -> None:
        """Parcel with zero outbound trips should have zero trips by all modes."""
        trips_outbound = np.array([0.0])
        ln_density = np.log(10.0 + 1.0)
        inter_dens = np.array([0.0])
        transit_access = np.array([0.0])
        ta, tt, tw, tb, *_ = _multinomial_logit(
            trips_outbound, ln_density, inter_dens, transit_access
        )
        np.testing.assert_array_equal(ta, np.zeros(1))
        np.testing.assert_array_equal(tt, np.zeros(1))
        np.testing.assert_array_equal(tw, np.zeros(1))
        np.testing.assert_array_equal(tb, np.zeros(1))

    def test_ln_density_zero_density(self) -> None:
        """ln(density + 1) should handle zero density gracefully."""
        density = 0.0
        result = np.log(density + 1.0)
        assert result == 0.0

    def test_transit_access_proxy_urban(self) -> None:
        """Urban/compat areas should have transit_access = 1.0."""
        categories = np.array(["urban", "compact", "standard", "rural"])
        expected = np.array([1.0, 1.0, 0.0, 0.0])
        result = np.where(np.isin(categories, ["urban", "compact"]), 1.0, 0.0)
        np.testing.assert_array_equal(result, expected)


# ════════════════════════════════════════════════════════════
#  Property-based tests for logit mode split invariants
# ════════════════════════════════════════════════════════════
#
# The pure function _multinomial_logit is shared with the dbt Python model.
# Tests the same import that dbt uses at runtime.
#
# Invariants verified:
#   - Mode shares sum to 1.0 for each parcel
#   - All shares are in [0, 1]
#   - Trips_by_mode sum to trips_outbound (conservation)
#   - Empty input returns empty output
#   - Zero trips produce zero trips by all modes
# ────────────────────────────────────────────────────────────


# ── Hypothesis strategy ────────────────────────────────────

_LOGIT_ARRAYS = st.integers(min_value=2, max_value=5).flatmap(
    lambda n: st.tuples(
        st.lists(
            st.floats(
                min_value=0, max_value=5000, allow_nan=False, allow_infinity=False
            ),
            min_size=n,
            max_size=n,
        ).map(np.array),  # trips_outbound
        st.lists(
            st.floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        ).map(np.array),  # ln_density
        st.lists(
            st.floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        ).map(np.array),  # intersection_density
        st.lists(
            st.integers(min_value=0, max_value=1),
            min_size=n,
            max_size=n,
        ).map(np.array),  # transit_access
    )
)


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_shares_sum_to_one(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Mode shares for each parcel must sum to 1.0."""
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    assume(np.sum(trips_out) > 0)
    *_, sa, st_, sw, sb = _multinomial_logit(
        trips_out, ln_dens, inter_dens, transit_acc
    )
    row_sums = sa + st_ + sw + sb
    assert np.all(np.abs(row_sums - 1.0) < 1e-10), (
        f"Shares don't sum to 1.0: {row_sums}"
    )


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_shares_in_unit_interval(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """All mode shares must be in [0, 1]."""
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    *_, sa, st_, sw, sb = _multinomial_logit(
        trips_out, ln_dens, inter_dens, transit_acc
    )
    for name, arr in [("auto", sa), ("transit", st_), ("walk", sw), ("bike", sb)]:
        assert np.all(arr >= 0), f"{name} shares have negatives: {arr}"
        assert np.all(arr <= 1.0 + 1e-10), f"{name} shares exceed 1.0: {arr}"


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_trip_conservation(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Sum of trips by mode must equal sum of outbound trips."""
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    assume(np.sum(trips_out) > 0)
    ta, tt, tw, tb, *_ = _multinomial_logit(trips_out, ln_dens, inter_dens, transit_acc)
    total_by_mode = np.sum(ta) + np.sum(tt) + np.sum(tw) + np.sum(tb)
    assert abs(total_by_mode - np.sum(trips_out)) < 1e-6, (
        f"Trips by mode sum={total_by_mode:.4f} != outbound sum={np.sum(trips_out):.4f}"
    )


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_non_negative_trips(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """All mode trip arrays must be non-negative."""
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    ta, tt, tw, tb, *_ = _multinomial_logit(trips_out, ln_dens, inter_dens, transit_acc)
    assert np.all(ta >= -1e-10), f"trips_auto has negatives: {ta}"
    assert np.all(tt >= -1e-10), f"trips_transit has negatives: {tt}"
    assert np.all(tw >= -1e-10), f"trips_walk has negatives: {tw}"
    assert np.all(tb >= -1e-10), f"trips_bike has negatives: {tb}"


@pytest.mark.slow
@settings(suppress_health_check=[HealthCheck.filter_too_much])
@given(_LOGIT_ARRAYS)
def test_logit_auto_dominates_defaults(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    # With default ASCs (auto = 0.0, transit = -0.35, walk = -0.50, bike = -0.40),
    # the auto utility has no built-in penalty while other modes do.
    # The assume(inter_dens <= 12) keeps walkability low enough that walk's
    # coefficient on ln_dens (~0.15) cannot overcome its ASC deficit.
    """With default ASCs, auto should dominate at moderate intersection density.
    At very high density (> ~25), walk can overtake auto.
    """
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    assume(np.sum(trips_out) > 0)
    # Only parcels with realistic intersection density; very high walkability can beat auto
    assume(np.all(inter_dens <= 12))
    *_, sa, st_, sw, sb = _multinomial_logit(
        trips_out, ln_dens, inter_dens, transit_acc
    )
    assume(np.max(sa) < 1e6)
    assert np.all(sa >= st_ - 1e-10), f"Auto share {sa} not >= transit share {st_}"
    assert np.all(sa >= sw - 1e-10), f"Auto share {sa} not >= walk share {sw}"
    assert np.all(sa >= sb - 1e-10), f"Auto share {sa} not >= bike share {sb}"


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_zero_trips(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Parcel with zero outbound trips should have zero trips by all modes."""
    trips_out, ln_dens, inter_dens, transit_acc = arrays
    zero_out = np.zeros_like(trips_out)
    ta, tt, tw, tb, *_ = _multinomial_logit(zero_out, ln_dens, inter_dens, transit_acc)
    assert np.all(ta == 0), f"trips_auto not zero: {ta}"
    assert np.all(tt == 0), f"trips_transit not zero: {tt}"
    assert np.all(tw == 0), f"trips_walk not zero: {tw}"
    assert np.all(tb == 0), f"trips_bike not zero: {tb}"


@pytest.mark.slow
@given(_LOGIT_ARRAYS)
def test_logit_empty_input(
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    """Empty input should return empty arrays for all eight outputs."""
    _trips, _ln, _id, _ta = arrays
    empty = np.array([], dtype=float)
    result = _multinomial_logit(empty, empty, empty, empty)
    for arr in result:
        assert len(arr) == 0, f"Expected empty array, got len {len(arr)}"
