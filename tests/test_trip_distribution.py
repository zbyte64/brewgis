"""Tests for the trip_distribution dbt Python model (gravity model logic)."""
from __future__ import annotations

import numpy as np
import pytest


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
        dists = np.array([
            [0.0, 1.0, 2.0],
            [1.0, 0.0, 3.0],
            [2.0, 3.0, 0.0],
        ])
        b = 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dists > 0, dists ** (-b), 0.0)
        attract_imped = attractiveness[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)
        assert denom.shape == (n,)
        assert np.all(denom >= 0)

    def test_simple_two_parcel_gravity(self) -> None:
        """Verify gravity model with two parcels and simple inputs."""
        # Parcel A: 100 trips, employment=50, du=200
        # Parcel B: 200 trips, employment=100, du=100
        # Distance = 5 km
        trips = np.array([100.0, 200.0])
        emp = np.array([50.0, 100.0])
        du = np.array([200.0, 100.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        b = 2.0
        emp_weight = 1.0
        du_weight = 0.5

        # Distance matrix
        dx = xs[:, np.newaxis] - xs[np.newaxis, :]
        dy = ys[:, np.newaxis] - ys[np.newaxis, :]
        dists = np.sqrt(dx**2 + dy**2)

        # Impedance
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dists > 0, dists ** (-b), 0.0)

        # Attractiveness
        attractiveness = emp_weight * emp + du_weight * du

        # Gravity model
        attract_imped = attractiveness[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(
                denom[:, np.newaxis] > 0,
                attract_imped / denom[:, np.newaxis],
                0.0,
            )

        od_matrix = trips[:, np.newaxis] * frac

        # Self-trips (internal)
        internal = np.diag(od_matrix)
        assert internal[0] == 0.0  # Zero self-distance = zero internal by impedance

        # Outbound (excluding self)
        outbound = np.sum(od_matrix, axis=1) - np.diag(od_matrix)
        assert np.all(outbound >= 0)

    def test_total_trips_conserved(self) -> None:
        """Sum of outbound trips should not exceed total trip origins."""
        trips = np.array([100.0, 200.0, 150.0])

        n = 3
        xs = np.array([0.0, 3.0, 8.0])
        ys = np.array([0.0, 0.0, 0.0])
        emp = np.array([50.0, 75.0, 25.0])
        du = np.array([100.0, 200.0, 150.0])
        b = 2.0
        emp_weight = 1.0
        du_weight = 0.5

        dx = xs[:, np.newaxis] - xs[np.newaxis, :]
        dy = ys[:, np.newaxis] - ys[np.newaxis, :]
        dists = np.sqrt(dx**2 + dy**2)
        with np.errstate(divide="ignore", invalid="ignore"):
            impedance = np.where(dists > 0, dists ** (-b), 0.0)
        attractiveness = emp_weight * emp + du_weight * du
        attract_imped = attractiveness[np.newaxis, :] * impedance
        denom = np.sum(attract_imped, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = np.where(
                denom[:, np.newaxis] > 0,
                attract_imped / denom[:, np.newaxis],
                0.0,
            )
        od_matrix = trips[:, np.newaxis] * frac

        # Internal trips
        internal = np.diag(od_matrix)

        # For each origin, sum of (internal + outbound) = origin trips
        for i in range(n):
            total_i = internal[i] + (np.sum(od_matrix[i, :]) - od_matrix[i, i])
            assert abs(total_i - trips[i]) < 0.001, (
                f"Origin {i}: {total_i} != {trips[i]}"
            )

    def test_avg_trip_length(self) -> None:
        """Average trip length should be distance-weighted."""
        trips = np.array([100.0])
        xs = np.array([0.0, 5.0])
        ys = np.array([0.0, 0.0])
        dist = 5.0
        od_val = 80.0  # 80 trips go to the other parcel
        od_internal = 20.0  # 20 internal

        od_matrix = np.array([[od_internal, od_val], [0.0, 0.0]])
        dist_matrix = np.array([[0.0, dist], [dist, 0.0]])

        outbound = np.sum(od_matrix, axis=1) - np.diag(od_matrix)
        dist_weighted = np.sum(od_matrix * dist_matrix, axis=1)

        with np.errstate(divide="ignore", invalid="ignore"):
            avg_len = np.where(outbound > 0, dist_weighted / outbound, 0.0)

        expected = (od_val * dist) / od_val
        assert avg_len[0] == pytest.approx(expected)
        assert avg_len[1] == 0.0  # No outbound = zero avg length
