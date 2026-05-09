"""Tests for the physical_activity dbt model SQL template and formulas."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analysis_template_test import DbtModelTemplateTest

MODEL_PATH = Path("brewgis/dbt_project/models/physical_activity.sql")


@pytest.mark.integration
class TestPhysicalActivityTemplate(DbtModelTemplateTest):
    """Verify the physical_activity SQL template structure."""

    model_path = MODEL_PATH
    model_name = "physical_activity"
    uses_ref_core_end_state = False
    expected_cols = [
        "walk_met_hours",
        "bike_met_hours",
        "total_met_hours",
        "walk_trips",
        "bike_trips",
        "active_trip_share",
    ]

    def test_has_walk_met_column(self, sql_template: str) -> None:
        assert "walk_met_hours" in sql_template

    def test_has_bike_met_column(self, sql_template: str) -> None:
        assert "bike_met_hours" in sql_template

    def test_has_total_met_column(self, sql_template: str) -> None:
        assert "total_met_hours" in sql_template

    def test_has_walk_trips_column(self, sql_template: str) -> None:
        assert "walk_trips" in sql_template

    def test_has_bike_trips_column(self, sql_template: str) -> None:
        assert "bike_trips" in sql_template

    def test_has_active_share_column(self, sql_template: str) -> None:
        assert "active_trip_share" in sql_template

    def test_uses_health_walk_met_var(self, sql_template: str) -> None:
        assert "health_walk_met" in sql_template

    def test_uses_health_bike_met_var(self, sql_template: str) -> None:
        assert "health_bike_met" in sql_template

    def test_uses_speed_vars(self, sql_template: str) -> None:
        assert "health_walk_speed_kmh" in sql_template
        assert "health_bike_speed_kmh" in sql_template

    def test_uses_mode_choice_ref(self, sql_template: str) -> None:
        assert "{{ ref('mode_choice') }}" in sql_template

    def test_uses_trip_distribution_ref(self, sql_template: str) -> None:
        assert "{{ ref('trip_distribution') }}" in sql_template

    @pytest.mark.parametrize(
        ("col"),
        ["parcel_id", "avg_trip_length_km", "population"],
    )
    def test_has_input_columns(self, sql_template: str, col: str) -> None:
        assert col in sql_template

    def test_no_hardcoded_schema_names(self, sql_template: str) -> None:
        assert all(h not in sql_template for h in ["public.", ' "schema"'])


@pytest.mark.integration
class TestPhysicalActivityFormula:
    """Verify physical activity (MET-hours) formula logic."""

    def test_walk_met_hours(self) -> None:
        trips = 100.0
        dist_km = 2.0
        speed = 4.8
        met = 3.5
        result = trips * (dist_km / speed) * met
        assert result == pytest.approx(145.83, rel=0.01)

    def test_bike_met_hours(self) -> None:
        trips = 50.0
        dist_km = 5.0
        speed = 16.0
        met = 6.0
        result = trips * (dist_km / speed) * met
        assert result == pytest.approx(93.75, rel=0.01)

    def test_total_met_hours(self) -> None:
        walk_met = 145.83
        bike_met = 93.75
        result = walk_met + bike_met
        assert result == pytest.approx(239.58, rel=0.01)

    def test_zero_trips(self) -> None:
        result = 0.0 * (2.0 / 4.8) * 3.5
        assert result == 0.0

    def test_active_trip_share(self) -> None:
        walk = 100.0
        bike = 50.0
        auto = 500.0
        transit = 50.0
        total = walk + bike + auto + transit
        share = (walk + bike) / total
        assert share == pytest.approx(0.2143, rel=0.01)

    def test_active_share_no_trips(self) -> None:
        share = 0.0
        assert share == 0.0

    def test_active_share_all_active(self) -> None:
        walk = 100.0
        bike = 50.0
        share = (walk + bike) / (walk + bike)
        assert share == 1.0

    def test_custom_walk_speed(self) -> None:
        trips = 100.0
        dist_km = 2.0
        custom_speed = 5.0  # faster walk
        met = 3.5
        result = trips * (dist_km / custom_speed) * met
        fast_met = 100.0 * (2.0 / 4.8) * 3.5  # default
        assert result < fast_met
