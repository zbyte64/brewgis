# ruff: noqa: ANN201, ARG002
"""Tests for PaintedCanvas model (EAV overrides).

These tests validate the model and its constraints, independent of the
SQL view layer (which is tested in test_canvas_view_manager.py).
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from tests.factories import PaintedCanvasFactory
from tests.factories import ScenarioFactory


@pytest.mark.models
class TestPaintedCanvasModel:
    """Direct model-level tests for PaintedCanvas."""

    def test_create_paint(self, db, scenario):
        """Can paint a feature column value."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=150.0,
        )
        assert paint.pk is not None
        assert paint.painted_value == 150.0
        assert paint.column_name == "du"
        assert paint.feature_id == "parcel-001"

    def test_unique_constraint(self, db, scenario):
        """Cannot paint the same (scenario, feature_id, column_name) twice."""
        PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=100.0,
        )
        with pytest.raises(IntegrityError):
            PaintedCanvasFactory(
                scenario=scenario,
                feature_id="parcel-001",
                column_name="du",
                painted_value=200.0,
            )

    def test_repaint_same_feature_different_column(self, db, scenario):
        """Same feature can have multiple columns painted."""
        paint_du = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=150.0,
        )
        paint_pop = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="pop",
            painted_value=300.0,
        )
        assert paint_du.pk != paint_pop.pk

    def test_different_scenarios_same_feature_column(self, db, workspace):
        """Different scenarios can independently paint the same feature+column."""
        s1 = ScenarioFactory(workspace=workspace)
        s2 = ScenarioFactory(workspace=workspace)

        paint1 = PaintedCanvasFactory(
            scenario=s1,
            feature_id="parcel-001",
            column_name="du",
            painted_value=100.0,
        )
        paint2 = PaintedCanvasFactory(
            scenario=s2,
            feature_id="parcel-001",
            column_name="du",
            painted_value=200.0,
        )

        assert paint1.pk != paint2.pk

    def test_painted_value_can_be_null(self, db, scenario):
        """painted_value can be NULL (to clear an override)."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=None,
        )
        assert paint.painted_value is None

    def test_update_existing_paint(self, db, scenario):
        """Can update an existing paint value."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=100.0,
        )
        paint.painted_value = 200.0
        paint.save()

        paint.refresh_from_db()
        assert paint.painted_value == 200.0

    def test_delete_paint_and_readd(self, db, scenario):
        """Can delete a paint and re-paint the same cell."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=100.0,
        )
        pk = paint.pk
        paint.delete()

        new_paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=300.0,
        )
        assert new_paint.pk != pk
        assert new_paint.painted_value == 300.0

    def test_multiple_features_in_same_scenario(self, db, scenario):
        """Multiple features can be painted in the same scenario."""
        for i in range(5):
            PaintedCanvasFactory(
                scenario=scenario,
                feature_id=f"parcel-{i:03d}",
                column_name="du",
                painted_value=float(100 + i * 10),
            )

        assert scenario.painted_features.count() == 5

    def test_painted_by_tracking(self, db, scenario, user):
        """Track which user painted the value."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=100.0,
            painted_by=user,
        )
        assert paint.painted_by == user

    def test_str_representation(self, db, scenario):
        """String representation includes scenario, feature, column, value."""
        paint = PaintedCanvasFactory(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            painted_value=150.0,
        )
        expected = f"PaintedCanvas[{scenario.pk}](parcel-001.du=150.0)"
        assert str(paint) == expected
