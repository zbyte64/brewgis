# ruff: noqa: ANN201
"""Tests for paint history and undo/redo functionality.

Covers PaintEvent model, event logging on paint operations,
undo_paint view, and paint_history view.
"""

from __future__ import annotations

import json

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import PaintEvent
from tests.factories import PaintedCanvasFactory
from tests.factories import ScenarioFactory
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory

UNDO_URL_NAME = "workspace:undo_paint"
HISTORY_URL_NAME = "workspace:paint_history"
PAINT_URL_NAME = "workspace:paint_features"
CLEAR_URL_NAME = "workspace:clear_paint"
BF_PAINT_URL_NAME = "workspace:paint_built_form"


# ── PaintEvent Model Tests ──────────────────────────────────────


@pytest.mark.models
class TestPaintEventModel:
    """Direct model-level tests for PaintEvent."""

    def test_create_paint_event(self, db, scenario, user):
        """Can create a paint event record."""
        event = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=100.0,
            new_value=150.0,
            painted_by=user,
            operation_type="paint",
            batch_id="batch-001",
        )
        assert event.pk is not None
        assert event.old_value == 100.0
        assert event.new_value == 150.0
        assert event.operation_type == "paint"
        assert event.undone_at is None

    def test_clear_event_logged(self, db, scenario, user):
        """Can create a clear event."""
        event = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=150.0,
            new_value=None,
            painted_by=user,
            operation_type="clear",
            batch_id="batch-002",
        )
        assert event.operation_type == "clear"
        assert event.new_value is None

    def test_built_form_event(self, db, scenario, user):
        """Can create a built_form event."""
        event = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=100.0,
            new_value=250.0,
            painted_by=user,
            operation_type="built_form",
            batch_id="batch-003",
        )
        assert event.operation_type == "built_form"

    def test_undo_event(self, db, scenario, user):
        """Can create an undo event."""
        event = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=150.0,
            new_value=100.0,
            painted_by=user,
            operation_type="undo",
            batch_id="batch-004",
        )
        assert event.operation_type == "undo"

    def test_ordering_recent_first(self, db, scenario, user):
        """Events are ordered by painted_at descending."""
        e1 = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=100.0,
            new_value=150.0,
            painted_by=user,
            operation_type="paint",
            batch_id="batch-005",
        )
        e2 = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="pop",
            old_value=200.0,
            new_value=300.0,
            painted_by=user,
            operation_type="paint",
            batch_id="batch-006",
        )
        events = list(PaintEvent.objects.filter(scenario=scenario))
        assert events[0] == e2
        assert events[1] == e1

    def test_str_representation(self, db, scenario, user):
        """String representation includes scenario, operation, feature, column, values."""
        event = PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=100.0,
            new_value=150.0,
            painted_by=user,
            operation_type="paint",
            batch_id="batch-007",
        )
        expected = f"PaintEvent[{scenario.pk}](Paint: parcel-001.du 100.0→150.0)"
        assert str(event) == expected

    def test_scenario_delete_cascades(self, db, scenario, user):
        """Deleting a scenario cascades to its paint events."""
        PaintEvent.objects.create(
            scenario=scenario,
            feature_id="parcel-001",
            column_name="du",
            old_value=100.0,
            new_value=150.0,
            painted_by=user,
            operation_type="paint",
            batch_id="batch-008",
        )
        pk = scenario.pk
        scenario.delete()
        assert PaintEvent.objects.filter(scenario__pk=pk).count() == 0


# ── Paint Event Logging Integration Tests ─────────────────────│──


@pytest.mark.views
class TestPaintLoggingIntegration(TestCase):
    """Tests that paint operations log PaintEvent records."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.paint_url = reverse(
            PAINT_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )
        self.clear_url = reverse(
            CLEAR_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )

    def test_paint_features_creates_events(self):
        """paint_features creates a PaintEvent for each feature."""
        response = self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1", "p2"], "column": "du", "value": 150.0}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["batch_id"] is not None

        events = PaintEvent.objects.filter(scenario=self.scenario)
        assert events.count() == 2
        assert events.filter(feature_id="p1").exists()
        assert events.filter(feature_id="p2").exists()
        assert all(e.operation_type == "paint" for e in events)
        assert all(e.new_value == 150.0 for e in events)
        assert all(e.old_value is None for e in events)  # No prior paint

    def test_paint_features_logs_old_value(self):
        """Re-painting logs the previous painted value as old_value."""
        # First paint
        PaintedCanvasFactory(
            scenario=self.scenario,
            feature_id="p1",
            column_name="du",
            painted_value=100.0,
        )
        # Re-paint
        response = self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 200.0}),
            content_type="application/json",
        )
        assert response.status_code == 200

        event = PaintEvent.objects.get(
            scenario=self.scenario, feature_id="p1", column_name="du"
        )
        assert event.old_value == 100.0
        assert event.new_value == 200.0

    def test_clear_paint_logs_events(self):
        """clear_paint creates a PaintEvent for each cleared column."""
        # Create some painted values to clear
        PaintedCanvasFactory(
            scenario=self.scenario,
            feature_id="p1",
            column_name="du",
            painted_value=100.0,
        )
        PaintedCanvasFactory(
            scenario=self.scenario,
            feature_id="p1",
            column_name="pop",
            painted_value=200.0,
        )
        # Clear all paint on p1
        response = self.client.post(
            self.clear_url,
            json.dumps({"features": ["p1"]}),
            content_type="application/json",
        )
        assert response.status_code == 200

        events = PaintEvent.objects.filter(scenario=self.scenario)
        assert events.count() == 2
        assert all(e.operation_type == "clear" for e in events)
        # old values captured before delete
        assert events.filter(column_name="du").first().old_value == 100.0
        assert events.filter(column_name="pop").first().old_value == 200.0

    def test_clear_no_paint_creates_no_events(self):
        """Clear on features with no paint generates no events."""
        response = self.client.post(
            self.clear_url,
            json.dumps({"features": ["p1"]}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert PaintEvent.objects.filter(scenario=self.scenario).count() == 0


# ── Paint History View Tests ────────────────────────────────────


@pytest.mark.views
class TestPaintHistoryView(TestCase):
    """Tests for the paint_history view."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.url = reverse(
            HISTORY_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )

        # Create some events
        for i in range(5):
            PaintEvent.objects.create(
                scenario=self.scenario,
                feature_id=f"p{i}",
                column_name="du",
                old_value=None,
                new_value=float(100 + i * 10),
                painted_by=self.user,
                operation_type="paint",
                batch_id=f"batch-{i}",
            )

    def test_returns_events_paginated(self):
        """Returns paint events paginated with defaults."""
        response = self.client.get(self.url)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["total"] == 5
        assert len(data["events"]) == 5  # limit is 50, we have 5
        assert data["events"][0]["feature_id"] == "p4"  # most recent first

    def test_limit_offset(self):
        """Respects limit and offset query params."""
        response = self.client.get(self.url + "?limit=2&offset=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) == 2
        assert data["events"][0]["feature_id"] == "p3"  # offset 1
        assert data["events"][1]["feature_id"] == "p2"

    def test_filter_by_feature_id(self):
        """Filters events by feature_id."""
        response = self.client.get(self.url + "?feature_id=p2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["events"][0]["feature_id"] == "p2"

    def test_event_shape(self):
        """Each event has expected fields."""
        response = self.client.get(self.url + "?limit=1")
        data = response.json()
        event = data["events"][0]
        assert "id" in event
        assert "feature_id" in event
        assert "column_name" in event
        assert "old_value" in event
        assert "new_value" in event
        assert "painted_by_name" in event
        assert "painted_at" in event
        assert "operation_type" in event
        assert "batch_id" in event
        assert "undone_at" in event

    def test_no_events(self):
        """Returns empty list when no events exist."""
        new_scenario = ScenarioFactory(workspace=self.workspace)
        url = reverse(
            HISTORY_URL_NAME,
            args=[self.workspace.pk, new_scenario.pk],
        )
        response = self.client.get(url)
        data = response.json()
        assert data["total"] == 0
        assert data["events"] == []

    def test_undone_at_reflected(self):
        """undone_at is populated when event is undone."""
        # Create an event, then mark it undone
        event = PaintEvent.objects.filter(scenario=self.scenario).first()
        from django.utils.timezone import now

        event.undone_at = now()
        event.save()

        response = self.client.get(self.url + "?limit=1")
        data = response.json()
        assert data["events"][0]["undone_at"] is not None

    def test_get_no_scenario(self) -> None:
        """Get history for a non-existent scenario PK returns 404."""
        bad_url = reverse(
            HISTORY_URL_NAME,
            args=[self.workspace.pk, 99999],
        )
        response = self.client.get(bad_url)
        assert response.status_code == 404


# ── Undo Paint View Tests ───────────────────────────────────────


@pytest.mark.views
class TestUndoPaintView(TestCase):
    """Tests for the undo_paint view."""

    def setUp(self):
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory()
        self.scenario = ScenarioFactory(workspace=self.workspace)
        self.paint_url = reverse(
            PAINT_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )
        self.clear_url = reverse(
            CLEAR_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )
        self.undo_url = reverse(
            UNDO_URL_NAME,
            args=[self.workspace.pk, self.scenario.pk],
        )

    def test_undo_paint_restores_old_value(self):
        """Undoing a paint restores the previous painted value."""
        # Paint du=100 first
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 100.0}),
            content_type="application/json",
        )
        # Re-paint du=200
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 200.0}),
            content_type="application/json",
        )
        # Get the event for the second paint
        event = (
            PaintEvent.objects.filter(
                scenario=self.scenario, feature_id="p1", column_name="du"
            )
            .order_by("-painted_at")
            .first()
        )
        assert event.old_value == 100.0
        assert event.new_value == 200.0

        # Undo the second paint
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": event.id}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        # Verify painted value was restored
        pc = PaintedCanvas.objects.get(
            scenario=self.scenario, feature_id="p1", column_name="du"
        )
        assert pc.painted_value == 100.0

        # Verify event was marked undone
        event.refresh_from_db()
        assert event.undone_at is not None

        # Verify undo event was logged
        undo_events = PaintEvent.objects.filter(
            scenario=self.scenario, operation_type="undo"
        )
        assert undo_events.count() == 1
        assert undo_events[0].old_value == 200.0
        assert undo_events[0].new_value == 100.0

    def test_undo_new_paint_deletes_paintedcanvas_row(self):
        """Undoing a paint where old_value was None deletes the PaintedCanvas row."""
        # Initial paint (no prior paint)
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 150.0}),
            content_type="application/json",
        )
        event = PaintEvent.objects.filter(
            scenario=self.scenario, operation_type="paint"
        ).first()
        assert event.old_value is None  # No prior paint

        # Undo
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": event.id}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # PaintedCanvas row should be deleted
        assert not PaintedCanvas.objects.filter(
            scenario=self.scenario, feature_id="p1", column_name="du"
        ).exists()

    def test_undo_clear_recreates_paintedcanvas(self):
        """Undoing a clear recreates the PaintedCanvas row."""
        # Paint
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 150.0}),
            content_type="application/json",
        )
        # Clear
        self.client.post(
            self.clear_url,
            json.dumps({"features": ["p1"]}),
            content_type="application/json",
        )
        assert not PaintedCanvas.objects.filter(
            scenario=self.scenario, feature_id="p1"
        ).exists()

        # Find the clear event
        clear_events = PaintEvent.objects.filter(
            scenario=self.scenario, operation_type="clear"
        )
        assert clear_events.count() == 1
        clear_event = clear_events.first()

        # Undo the clear
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": clear_event.id}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # PaintedCanvas row should be restored
        pc = PaintedCanvas.objects.get(
            scenario=self.scenario, feature_id="p1", column_name="du"
        )
        assert pc.painted_value == 150.0

    def test_undo_batch_by_batch_id(self):
        """Undoing by batch_id undoes all events in that batch."""
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1", "p2"], "column": "du", "value": 200.0}),
            content_type="application/json",
        )

        # Get the batch_id from either event
        batch_id = PaintEvent.objects.filter(scenario=self.scenario).first().batch_id

        # Undo by batch_id
        response = self.client.post(
            self.undo_url,
            json.dumps({"batch_id": batch_id}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Both features should be back to no paint
        assert not PaintedCanvas.objects.filter(
            scenario=self.scenario, feature_id="p1", column_name="du"
        ).exists()
        assert not PaintedCanvas.objects.filter(
            scenario=self.scenario, feature_id="p2", column_name="du"
        ).exists()

    def test_undo_already_undone_returns_404(self):
        """Undoing an already-undone event returns 404."""
        self.client.post(
            self.paint_url,
            json.dumps({"features": ["p1"], "column": "du", "value": 150.0}),
            content_type="application/json",
        )
        event = PaintEvent.objects.filter(
            scenario=self.scenario, operation_type="paint"
        ).first()

        # First undo works
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": event.id}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Second undo fails
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": event.id}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_undo_nonexistent_event_returns_404(self):
        """Undoing a nonexistent event ID returns 404."""
        response = self.client.post(
            self.undo_url,
            json.dumps({"event_id": 99999}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_undo_requires_event_id_or_batch_id(self):
        """Undo requires either event_id or batch_id."""
        response = self.client.post(
            self.undo_url,
            json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_undo_no_scenario(self) -> None:
        """Post undo for a non-existent scenario PK returns 404."""
        bad_url = reverse(
            UNDO_URL_NAME,
            args=[self.workspace.pk, 99999],
        )
        response = self.client.post(
            bad_url,
            json.dumps({"event_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_undo_no_workspace(self) -> None:
        """Post undo for a non-existent workspace PK returns 404."""
        bad_url = reverse(
            UNDO_URL_NAME,
            args=[99999, self.scenario.pk],
        )
        response = self.client.post(
            bad_url,
            json.dumps({"event_id": 1}),
            content_type="application/json",
        )
        assert response.status_code == 404
