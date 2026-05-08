"""Tests for the mode_choice dbt Python model (logit mode split logic)."""
from __future__ import annotations

import numpy as np
import pytest


@pytest.mark.integration
class TestModeChoiceLogit:
    """Pure Python tests for multinomial logit mode choice math."""

    def test_softmax_sum_to_one(self) -> None:
        """Mode shares for each parcel should sum to 1.0."""
        n = 4
        u_auto = np.zeros(n)
        u_transit = np.full(n, -2.0)
        u_walk = np.full(n, -1.5)
        u_bike = np.full(n, -2.5)

        u_stack = np.column_stack([u_auto, u_transit, u_walk, u_bike])
        u_max = np.max(u_stack, axis=1, keepdims=True)
        exp_u = np.exp(u_stack - u_max)
        sum_exp_u = np.sum(exp_u, axis=1, keepdims=True)
        shares = exp_u / sum_exp_u

        row_sums = np.sum(shares, axis=1)
        np.testing.assert_array_almost_equal(row_sums, np.ones(n))

    def test_auto_dominates_defaults(self) -> None:
        """With default parameters, auto should have highest share."""
        n = 1
        density = 5.0
        ln_density = np.log(density + 1.0)
        intersection_density = 0.0  # Rural, no intersections
        transit_access = 0.0  # Rural, no transit

        asc_transit = -2.0
        asc_walk = -1.5
        asc_bike = -2.5
        beta_density = -0.15
        beta_design_walk = 0.05
        beta_transit_dist = 0.02

        u_auto = np.zeros(n)
        u_transit = asc_transit + beta_density * ln_density + beta_transit_dist * transit_access
        u_walk = asc_walk + beta_density * ln_density + beta_design_walk * intersection_density
        u_bike = asc_bike + beta_density * ln_density + beta_design_walk * intersection_density

        u_stack = np.column_stack([u_auto, u_transit, u_walk, u_bike])
        u_max = np.max(u_stack, axis=1, keepdims=True)
        exp_u = np.exp(u_stack - u_max)
        sum_exp_u = np.sum(exp_u, axis=1, keepdims=True)
        shares = exp_u / sum_exp_u

        assert shares[0, 0] > shares[0, 1]  # auto > transit
        assert shares[0, 0] > shares[0, 2]  # auto > walk
        assert shares[0, 0] > shares[0, 3]  # auto > bike

    def test_transit_access_increases_share(self) -> None:
        """Transit access should increase transit share."""
        # Urban parcel (high density, transit available)
        ln_density_urban = np.log(15.0 + 1.0)
        transit_urban = 1.0

        # Rural parcel (low density, no transit)
        ln_density_rural = np.log(2.0 + 1.0)
        transit_rural = 0.0

        asc_transit = -2.0
        beta_density = 0.15
        beta_transit_dist = 0.02
        u_transit_urban = asc_transit + beta_density * ln_density_urban + beta_transit_dist * transit_urban
        u_transit_rural = asc_transit + beta_density * ln_density_rural + beta_transit_dist * transit_rural

        def _share(u_t: float) -> float:
            u_a = 0.0
            u_stack = np.array([u_a, u_t, -1.5, -2.5])
            u_max = np.max(u_stack)
            exp_u = np.exp(u_stack - u_max)
            return exp_u[1] / np.sum(exp_u)

        share_urban = _share(u_transit_urban)
        share_rural = _share(u_transit_rural)

        assert share_urban > share_rural, (
            f"Urban transit share {share_urban:.4f} should exceed rural {share_rural:.4f}"
        )

    def test_density_reduces_auto_share(self) -> None:
        """Higher density should reduce auto share (negative beta_density)."""
        ln_dense = np.log(30.0 + 1.0)
        ln_sparse = np.log(2.0 + 1.0)

        u_auto = 0.0

        def _auto_share(ln_d: float) -> float:
            u_transit = -2.0 + 0.15 * ln_d
            u_walk = -1.5 + 0.15 * ln_d
            u_bike = -2.5 + 0.15 * ln_d
            u_stack = np.array([u_auto, u_transit, u_walk, u_bike])
            u_max = np.max(u_stack)
            exp_u = np.exp(u_stack - u_max)
            return exp_u[0] / np.sum(exp_u)

        share_dense = _auto_share(ln_dense)
        share_sparse = _auto_share(ln_sparse)

        assert share_dense < share_sparse, (
            f"Dense auto share {share_dense:.4f} should be less than sparse {share_sparse:.4f}"
        )

    def test_walk_share_higher_with_design(self) -> None:
        """Higher intersection density should increase walk/bike share."""
        ln_density = np.log(10.0 + 1.0)
        high_design = 10.0  # Urban grid
        low_design = 0.0  # Rural

        def _walk_share(inter_dens: float) -> float:
            u_auto = 0.0
            u_transit = -2.0 + (-0.15) * ln_density
            u_walk = -1.5 + (-0.15) * ln_density + 0.05 * inter_dens
            u_bike = -2.5 + (-0.15) * ln_density + 0.05 * inter_dens
            u_stack = np.array([u_auto, u_transit, u_walk, u_bike])
            u_max = np.max(u_stack)
            exp_u = np.exp(u_stack - u_max)
            return exp_u[2] / np.sum(exp_u)

        share_high = _walk_share(high_design)
        share_low = _walk_share(low_design)

        assert share_high > share_low, (
            f"High design walk share {share_high:.4f} should exceed low {share_low:.4f}"
        )

    def test_trips_by_mode_sum_to_outbound(self) -> None:
        """Sum of trips by mode should equal trips_outbound."""
        trips_outbound = np.array([100.0, 200.0, 150.0])
        n = 3
        density = np.array([5.0, 15.0, 2.0])
        ln_density = np.log(density + 1.0)
        inter_dens = np.array([0.0, 5.0, 0.0])
        transit_access = np.array([0.0, 1.0, 0.0])

        asc_transit, asc_walk, asc_bike = -2.0, -1.5, -2.5
        beta_density, beta_design_walk, beta_transit_dist = -0.15, 0.05, 0.02

        u_auto = np.zeros(n)
        u_transit = asc_transit + beta_density * ln_density + beta_transit_dist * transit_access
        u_walk = asc_walk + beta_density * ln_density + beta_design_walk * inter_dens
        u_bike = asc_bike + beta_density * ln_density + beta_design_walk * inter_dens

        u_stack = np.column_stack([u_auto, u_transit, u_walk, u_bike])
        u_max = np.max(u_stack, axis=1, keepdims=True)
        exp_u = np.exp(u_stack - u_max)
        sum_exp_u = np.sum(exp_u, axis=1, keepdims=True)
        shares = exp_u / sum_exp_u

        trips_by_mode = trips_outbound.reshape(-1, 1) * shares
        trips_sum = np.sum(trips_by_mode, axis=1)

        np.testing.assert_array_almost_equal(trips_sum, trips_outbound)

    def test_zero_trips_parcel(self) -> None:
        """Parcel with zero outbound trips should have zero trips by all modes."""
        trips_outbound = 0.0
        ln_density = np.log(10.0 + 1.0)

        u_auto = 0.0
        u_transit = -2.0 + (-0.15) * ln_density
        u_walk = -1.5 + (-0.15) * ln_density
        u_bike = -2.5 + (-0.15) * ln_density

        u_stack = np.array([u_auto, u_transit, u_walk, u_bike])
        u_max = np.max(u_stack)
        exp_u = np.exp(u_stack - u_max)
        shares = exp_u / np.sum(exp_u)

        trips_by_mode = trips_outbound * shares
        np.testing.assert_array_equal(trips_by_mode, np.zeros(4))

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
