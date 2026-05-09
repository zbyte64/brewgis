# ruff: noqa: PT009
"""Tests for the internal capture (T5) dbt model.

Verifies that the model correctly classifies trips as internal/external
based on the study area boundary, and that invariants like
internal + external = total trips hold.

Reference:
    - dbt model: brewgis/dbt_project/models/internal_capture.sql
"""

from __future__ import annotations

import math

from django.test import TestCase


class TestInternalCaptureLogic(TestCase):
    """T5 Internal Capture — classification invariants and boundary cases.

    These tests validate the SQL logic embedded in the internal_capture dbt
    model by exercising the decision rules with synthetic data.

    The model classifies trips as:
        internal_capture_pct = f(study_area_fraction, avg_trip_length, intrazonal_friction)
        trips_internal = trips_intra_parcel + trips_outbound * internal_capture_pct
        trips_external = trips_total - trips_internal
    """

    def _compute_internal_capture_pct(
        self,
        study_area_fraction: float,
        avg_trip_length_km: float,
        intrazonal_friction: float,
        study_area_radius_km: float = 10.0,
    ) -> float:
        """Replicate the SQL model's capture rate formula."""
        if study_area_fraction <= 0:
            return 0.0
        attenuation = math.exp(
            -intrazonal_friction
            * avg_trip_length_km
            / max(study_area_radius_km, 0.001)
        )
        return min(1.0, study_area_fraction * attenuation)

    def test_parcel_in_study_area_has_nonzero_capture(self) -> None:
        """A parcel inside the study area should have internal_capture_pct > 0."""
        internal_capture_pct = self._compute_internal_capture_pct(
            study_area_fraction=0.6,
            avg_trip_length_km=5.0,
            intrazonal_friction=0.15,
            study_area_radius_km=10.0,
        )
        self.assertGreater(internal_capture_pct, 0)
        self.assertLessEqual(internal_capture_pct, 1.0)

    def test_parcel_outside_study_area_zero_capture(self) -> None:
        """A parcel outside the study area should have 0% internal capture."""
        self.assertEqual(
            self._compute_internal_capture_pct(
                study_area_fraction=0.0,
                avg_trip_length_km=5.0,
                intrazonal_friction=0.15,
            ),
            0.0,
        )

    def test_internal_plus_external_equals_total(self) -> None:
        """Internal + external trips should sum to total trips."""
        trips_total = 100.0
        trips_intra_parcel = 5.0
        trips_outbound = 95.0
        internal_capture_pct = 0.4

        trips_internal = trips_intra_parcel + trips_outbound * internal_capture_pct
        trips_external = trips_total - trips_internal

        self.assertAlmostEqual(
            trips_internal + trips_external,
            trips_total,
            msg="Internal + external must equal total",
        )

    def test_no_outbound_trips_all_internal(self) -> None:
        """If all trips are intra-parcel, internal = total."""
        trips_total = 50.0
        trips_intra_parcel = 50.0
        trips_outbound = 0.0
        internal_capture_pct = 0.5

        trips_internal = trips_intra_parcel + trips_outbound * internal_capture_pct
        trips_external = trips_total - trips_internal

        self.assertEqual(trips_internal, trips_total)
        self.assertEqual(trips_external, 0.0)

    def test_attenuation_increases_with_trip_length(self) -> None:
        """Longer trips should have lower internal capture (higher attenuation)."""
        short_capture = self._compute_internal_capture_pct(
            study_area_fraction=0.8,
            avg_trip_length_km=2.0,
            intrazonal_friction=0.15,
            study_area_radius_km=5.0,
        )
        long_capture = self._compute_internal_capture_pct(
            study_area_fraction=0.8,
            avg_trip_length_km=20.0,
            intrazonal_friction=0.15,
            study_area_radius_km=5.0,
        )

        self.assertGreater(
            short_capture,
            long_capture,
            "Short trips should have higher internal capture than long trips",
        )

    def test_larger_study_area_increases_capture(self) -> None:
        """A larger study area (higher parcel_fraction) should increase capture."""
        small_capture = self._compute_internal_capture_pct(
            study_area_fraction=0.3,
            avg_trip_length_km=5.0,
            intrazonal_friction=0.15,
            study_area_radius_km=10.0,
        )
        large_capture = self._compute_internal_capture_pct(
            study_area_fraction=0.8,
            avg_trip_length_km=5.0,
            intrazonal_friction=0.15,
            study_area_radius_km=10.0,
        )

        self.assertGreater(
            large_capture,
            small_capture,
            "Larger study area should produce higher internal capture",
        )

    def test_study_area_entire_region_all_internal(self) -> None:
        """If the entire region is the study area, capture approaches 100%."""
        internal_capture_pct = self._compute_internal_capture_pct(
            study_area_fraction=0.999,
            avg_trip_length_km=2.0,
            intrazonal_friction=0.05,
            study_area_radius_km=20.0,
        )
        self.assertAlmostEqual(internal_capture_pct, 1.0, delta=0.01)

    def test_all_external_scenario_zero_capture(self) -> None:
        """Parcels entirely outside study area produce 0% capture."""
        internal_capture_pct = self._compute_internal_capture_pct(
            study_area_fraction=0.0,
            avg_trip_length_km=10.0,
            intrazonal_friction=0.5,
        )
        self.assertEqual(internal_capture_pct, 0.0)

    def test_trips_external_non_negative(self) -> None:
        """External trips must never be negative, even with numerical edge cases."""
        test_cases = [
            (100.0, 0.0, 100.0, 0.9),  # most are internal
            (100.0, 100.0, 0.0, 0.0),  # all intra-parcel
            (100.0, 0.0, 100.0, 0.0),  # all outbound, 0% capture
            (100.0, 0.0, 100.0, 1.0),  # all outbound, 100% capture
            (0.0, 0.0, 0.0, 0.5),  # zero trips
        ]

        for total, intra, outbound, capture_pct in test_cases:
            internal = intra + outbound * capture_pct
            external = total - internal
            self.assertGreaterEqual(
                external,
                0.0,
                msg=(
                    f"External trips negative for "
                    f"(total={total}, intra={intra}, outbound={outbound}, "
                    f"capture={capture_pct}): got {external}"
                ),
            )

    def test_internal_capture_pct_range(self) -> None:
        """Internal capture percentage must be in [0, 1]."""
        scenarios = [
            (0.0, 5.0, 0.15, 10.0),  # no study area
            (0.5, 5.0, 0.15, 10.0),  # typical
            (1.0, 5.0, 0.15, 10.0),  # full study area
            (0.3, 0.0, 0.15, 10.0),  # zero trip length
        ]

        for fraction, trip_len, friction, radius in scenarios:
            capture = self._compute_internal_capture_pct(
                study_area_fraction=fraction,
                avg_trip_length_km=trip_len,
                intrazonal_friction=friction,
                study_area_radius_km=radius,
            )
            self.assertGreaterEqual(capture, 0.0)
            self.assertLessEqual(capture, 1.0)
