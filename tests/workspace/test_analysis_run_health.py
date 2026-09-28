# ruff: noqa: ANN201
"""Tests for analysis-run liveness: the heartbeat a running run leaves behind,
and the reconciliation that records an abandoned run as failed."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from brewgis.workspace.analysis import run_health
from brewgis.workspace.analysis.run_health import abandonment
from brewgis.workspace.analysis.run_health import reconcile_abandoned_run
from brewgis.workspace.analysis.run_health import reconcile_abandoned_runs
from brewgis.workspace.analysis.run_health import run_heartbeat
from brewgis.workspace.models import AnalysisRun
from tests.factories import AnalysisRunFactory

BUDGET = timedelta(seconds=settings.ANALYSIS_TASK_TIME_LIMIT)


def _backdate_created_at(run: AnalysisRun, when) -> AnalysisRun:
    """Move *run*'s ``created_at`` back — ``auto_now_add`` ignores a passed value."""
    AnalysisRun.objects.filter(pk=run.pk).update(created_at=when)
    run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestAbandonment:
    """Which runs read as having lost their executor, and why."""

    def test_run_still_being_pinged_is_not_abandoned(self):
        run = AnalysisRunFactory(
            status="running",
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )
        assert abandonment(run) is None

    def test_running_run_whose_ping_went_quiet_is_abandoned(self):
        run = AnalysisRunFactory(
            status="running",
            started_at=timezone.now() - timedelta(minutes=10),
            heartbeat_at=timezone.now() - timedelta(minutes=5),
        )
        found = abandonment(run)

        assert found is not None
        assert "Abandoned" in found.reason
        # The executor is known to have stopped one stale window after its last
        # ping — not whenever the reader happened to notice.
        assert found.stopped_at == run.heartbeat_at + timedelta(
            seconds=run_health.STALE_HEARTBEAT_SECONDS
        )

    def test_running_run_outliving_its_task_budget_reads_as_a_timeout(self):
        run = AnalysisRunFactory(
            status="running",
            started_at=timezone.now() - BUDGET - timedelta(hours=1),
            heartbeat_at=timezone.now() - timedelta(minutes=5),
        )
        found = abandonment(run)

        assert found is not None
        assert "Timed out" in found.reason

    def test_running_run_without_a_heartbeat_falls_back_to_its_start(self):
        """Rows predating heartbeats (and runs whose thread was skipped) are
        judged on ``started_at``, so one just started is left alone."""
        run = AnalysisRunFactory(status="running", started_at=timezone.now())
        run.refresh_from_db()
        assert run.heartbeat_at is None
        assert abandonment(run) is None

    def test_running_run_without_a_heartbeat_is_dated_when_it_was_noticed(self):
        """Nothing is known past a legacy row's start, so its death is not
        back-dated to a moment the run never reported."""
        run = AnalysisRunFactory(
            status="running", started_at=timezone.now() - timedelta(minutes=10)
        )
        run.refresh_from_db()
        assert run.heartbeat_at is None

        found = abandonment(run)

        assert found is not None
        assert found.stopped_at > run.started_at + timedelta(minutes=1)
        assert found.stopped_at <= timezone.now()

    def test_queued_run_is_left_alone_within_the_budget(self):
        run = AnalysisRunFactory(status="pending")
        assert abandonment(run) is None

    def test_queued_run_that_outlived_the_budget_never_started(self):
        run = _backdate_created_at(
            AnalysisRunFactory(status="pending"),
            timezone.now() - BUDGET - timedelta(hours=1),
        )
        found = abandonment(run)

        assert found is not None
        assert "Never started" in found.reason
        assert found.stopped_at <= timezone.now()

    def test_finished_run_is_never_abandoned(self):
        for status in ("completed", "failed"):
            run = AnalysisRunFactory(
                status=status,
                started_at=timezone.now() - timedelta(days=2),
                completed_at=timezone.now() - timedelta(days=2),
                heartbeat_at=timezone.now() - timedelta(days=2),
            )
            assert abandonment(run) is None


@pytest.mark.django_db
class TestReconcileAbandonedRun:
    """Recording an abandoned run, and leaving every other run alone."""

    def _abandoned(self) -> AnalysisRun:
        return AnalysisRunFactory(
            status="running",
            started_at=timezone.now() - timedelta(minutes=30),
            heartbeat_at=timezone.now() - timedelta(minutes=10),
        )

    def test_records_the_run_as_failed_with_its_cause(self):
        run = self._abandoned()

        returned = reconcile_abandoned_run(run)

        assert returned is run
        assert run.status == "failed"
        assert "Abandoned" in run.failure_cause
        assert run.completed_at is not None
        run.refresh_from_db()
        assert run.status == "failed"
        assert "Abandoned" in run.failure_cause

    def test_leaves_a_live_run_untouched(self):
        run = AnalysisRunFactory(
            status="running",
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )

        assert reconcile_abandoned_run(run) is run
        assert run.failure_cause == ""
        run.refresh_from_db()
        assert run.status == "running"

    def test_does_not_overwrite_a_status_the_run_reached_meanwhile(self):
        """Two pollers can reconcile the same run at once; the loser must not
        clobber what the winner — or the run's real executor — wrote."""
        run = self._abandoned()
        stale_copy = AnalysisRun.objects.get(pk=run.pk)
        AnalysisRun.objects.filter(pk=run.pk).update(
            status="completed", completed_at=timezone.now()
        )

        returned = reconcile_abandoned_run(stale_copy)

        assert returned.status == "completed"
        assert AnalysisRun.objects.get(pk=run.pk).status == "completed"
        assert AnalysisRun.objects.get(pk=run.pk).failure_cause == ""

    def test_reconciles_every_run_in_a_list(self):
        abandoned = self._abandoned()
        live = AnalysisRunFactory(
            status="running",
            started_at=timezone.now(),
            heartbeat_at=timezone.now(),
        )

        reconcile_abandoned_runs([abandoned, live])

        assert abandoned.status == "failed"
        assert live.status == "running"


@pytest.mark.django_db(transaction=True)
def test_run_heartbeat_pings_the_run_while_the_block_runs():
    """The ping has to come from another connection to be visible to readers."""
    run = AnalysisRunFactory(status="running", started_at=timezone.now())
    run.refresh_from_db()
    assert run.heartbeat_at is None

    with run_heartbeat(run.pk, interval=0.02):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run.refresh_from_db()
            if run.heartbeat_at is not None:
                break
            time.sleep(0.02)

    assert run.heartbeat_at is not None


@pytest.mark.django_db(transaction=True)
def test_run_heartbeat_stops_pinging_when_the_block_exits():
    run = AnalysisRunFactory(status="running", started_at=timezone.now())

    with run_heartbeat(run.pk, interval=0.02):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run.refresh_from_db()
            if run.heartbeat_at is not None:
                break
            time.sleep(0.02)

    # Two settle windows: any straggling tick lands in the first one.
    time.sleep(0.3)
    run.refresh_from_db()
    settled = run.heartbeat_at
    time.sleep(0.3)
    run.refresh_from_db()
    assert run.heartbeat_at == settled


@pytest.mark.django_db
def test_run_heartbeat_is_a_no_op_inside_an_atomic_block():
    """The in-request execution holds its own run row uncommitted, so a ping
    from another connection could only block on it — and no reader can see the
    row until the request commits."""
    run = AnalysisRunFactory(status="running", started_at=timezone.now())

    with transaction.atomic(), run_heartbeat(run.pk, interval=0.02):
        time.sleep(0.2)

    assert AnalysisRun.objects.get(pk=run.pk).heartbeat_at is None
