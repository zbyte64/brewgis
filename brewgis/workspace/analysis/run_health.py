"""Liveness of an ``AnalysisRun`` — its heartbeat, and reconciling a lost one.

A run is executed either by a Celery worker (``run_analysis_task``) or
synchronously in-process (the MCP server, the full-page launcher). Both paths
write their own terminal status — ``completed``, or ``failed`` with a cause —
so a row that stays ``pending``/``running`` is one whose executor never got to
write: the worker was killed (Celery's hard time limit, a container restart,
the dev autoreloader, an OOM kill) or the dispatch never reached a worker at
all. Nothing else in the stack notices, and every reader of a run's status
polls while it reads ``pending``/``running`` — so one lost worker leaves every
analysis card in the map view spinning for as long as nobody looks at the
database.

Hence the heartbeat: while a run executes, :func:`run_heartbeat` pings its own
row every :data:`HEARTBEAT_INTERVAL_SECONDS`. Readers then call
:func:`reconcile_abandoned_run`, which records a run whose ping has gone quiet
as ``failed`` with an actionable cause. Two properties make that safe:

- a false positive corrects itself — the executor writes the run's real status
  when it finishes, and the reconciler only ever replaces ``pending``/
  ``running``, never a status a run has already reached;
- the reconciliation itself is a conditional UPDATE keyed on the status the
  reader saw, so concurrent pollers cannot both write it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import threading
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import DatabaseError
from django.db import close_old_connections
from django.db import transaction
from django.utils import timezone

from brewgis.workspace.models import AnalysisRun

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

LIVE_STATUSES = ("pending", "running")
"""Statuses of a run that is supposed to have an executor; the rest are final."""

HEARTBEAT_INTERVAL_SECONDS = 15
"""How often a run that is executing pings its own row."""

STALE_HEARTBEAT_SECONDS = 4 * HEARTBEAT_INTERVAL_SECONDS
"""Silence after which a run's executor is presumed gone.

Four intervals, so one missed tick (lock contention, a database blip) can't
declare a live run abandoned. The cost of a false positive is one wrong status
until the run really finishes, and the cost of a false negative is a card that
polls forever — hence a much shorter window than the run's own budget.
"""


_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


def _budget() -> timedelta:
    """The longest Celery lets one analysis task run before killing its worker."""
    return timedelta(seconds=settings.ANALYSIS_TASK_TIME_LIMIT)


def _duration_text(delta: timedelta) -> str:
    """Render *delta* for a run's cause text, e.g. ``"45 s"`` or ``"16 h"``."""
    seconds = int(delta.total_seconds())
    if seconds < _SECONDS_PER_MINUTE:
        return f"{seconds} s"
    if seconds < _SECONDS_PER_HOUR:
        return f"{seconds // _SECONDS_PER_MINUTE} min"
    return f"{round(seconds / _SECONDS_PER_HOUR)} h"


# ─────────────────────────────────────────────────────────────────────
#  Writer side — the heartbeat a running analysis leaves behind
# ─────────────────────────────────────────────────────────────────────


def _ping(run_pk: int) -> None:
    """Record one heartbeat for *run_pk*.

    Filtered on ``status="running"``: a tick that lands after the run finished
    must not touch a row that already reached its real status.
    """
    try:
        AnalysisRun.objects.filter(pk=run_pk, status="running").update(
            heartbeat_at=timezone.now()
        )
    except DatabaseError:
        # A database blip must not take the analysis down with it — the ping is
        # advisory, and the next tick retries. Dropping the connections that
        # just failed is what lets that retry actually reach the database.
        logger.warning("Heartbeat for AnalysisRun #%s failed", run_pk, exc_info=True)
        close_old_connections()


def _beat(run_pk: int, interval: float, stop: threading.Event) -> None:
    """Ping *run_pk* every *interval* seconds until *stop* is set."""
    while not stop.wait(interval):
        _ping(run_pk)
    close_old_connections()


@contextlib.contextmanager
def run_heartbeat(
    run_pk: int, *, interval: float = HEARTBEAT_INTERVAL_SECONDS
) -> Iterator[None]:
    """Keep *run_pk*'s heartbeat fresh for the duration of the block.

    No-op inside an atomic block: that is the in-request execution (the
    full-page multi-module launcher), which holds its own run row uncommitted.
    A ping from another connection could only block on that row's lock, and no
    reader can see the row until the request commits — by which point the run
    has a terminal status and nothing needs reconciling.
    """
    if transaction.get_connection().in_atomic_block:
        yield
        return

    stop = threading.Event()
    threading.Thread(
        target=_beat,
        args=(run_pk, interval, stop),
        name=f"analysis-heartbeat-{run_pk}",
        daemon=True,
    ).start()
    try:
        yield
    finally:
        stop.set()


# ─────────────────────────────────────────────────────────────────────
#  Reader side — noticing, and recording, a run that lost its executor
# ─────────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Abandonment:
    """Why a run has no executor left, and when its executor stopped."""

    reason: str
    stopped_at: datetime


def _pending_abandonment(run: AnalysisRun, now: datetime) -> Abandonment | None:
    """Why a *pending* run never reached a worker, if it clearly didn't.

    Nothing distinguishes a run still queued behind another analysis from one
    whose message the broker dropped — both read ``pending`` — so the task
    budget is the only bound. Past it, the run has waited as long as any single
    analysis may run; a run that is genuinely still queued and later starts
    overwrites this with its own real status.
    """
    queued_for = now - run.created_at
    if queued_for <= _budget():
        return None
    return Abandonment(
        reason=(
            f"Never started: no worker picked this run up within the "
            f"{_duration_text(_budget())} an analysis is allowed — it has been queued "
            f"for {_duration_text(queued_for)}, so its dispatch was lost or no worker "
            "is running. Re-run the analysis."
        ),
        stopped_at=now,
    )


def _running_abandonment(run: AnalysisRun, now: datetime) -> Abandonment | None:
    """Why a *running* run lost its executor, if its heartbeat has gone quiet."""
    # ``created_at`` is the fallback for a run started before heartbeats
    # existed, whose row carries no ping to compare against.
    last_ping = run.heartbeat_at or run.started_at or run.created_at
    quiet_for = now - last_ping
    if quiet_for <= timedelta(seconds=STALE_HEARTBEAT_SECONDS):
        return None

    # With a ping to go on, the executor stopped one stale window after it —
    # the silence itself dates the death. Without one (a row predating
    # heartbeats) nothing is known past the run's start, so it is dated when
    # this reader noticed instead of inventing a moment it never observed.
    stopped_at = (
        last_ping + timedelta(seconds=STALE_HEARTBEAT_SECONDS)
        if run.heartbeat_at
        else now
    )
    if run.started_at and last_ping - run.started_at > _budget():
        reason = (
            f"Timed out: this run passed the {_duration_text(_budget())} limit Celery "
            "gives an analysis task, so its worker was killed before it could record "
            "the result. Re-run the analysis."
        )
    else:
        reason = (
            f"Abandoned: the worker running this analysis stopped reporting "
            f"{_duration_text(quiet_for)} ago without recording a result — it was "
            "killed, restarted, or ran out of memory. Re-run the analysis."
        )
    return Abandonment(reason=reason, stopped_at=stopped_at)


def abandonment(run: AnalysisRun, *, now: datetime | None = None) -> Abandonment | None:
    """Why *run* has no executor left — or None while it is live or final."""
    if run.status not in LIVE_STATUSES:
        return None
    now = now or timezone.now()
    if run.status == "pending":
        return _pending_abandonment(run, now)
    return _running_abandonment(run, now)


def reconcile_abandoned_run(
    run: AnalysisRun, *, now: datetime | None = None
) -> AnalysisRun:
    """Record *run* as failed when nothing is executing it any more.

    Returns *run* itself with its status updated, so a caller can keep
    rendering the object it already fetched. Readers of a run's status call
    this so the map's analysis cards stop polling a run whose worker is gone and
    show what happened instead.

    The write is a conditional UPDATE keyed on the status this reader saw:
    when two pollers reconcile the same run at once, the second one's UPDATE
    matches nothing and it re-reads the row the first one wrote instead of
    overwriting a status the run has since reached.
    """
    found = abandonment(run, now=now)
    if found is None:
        return run

    healed = AnalysisRun.objects.filter(pk=run.pk, status=run.status).update(
        status="failed",
        failure_cause=found.reason,
        completed_at=found.stopped_at,
    )
    if not healed:
        run.refresh_from_db()
        return run

    logger.warning("AnalysisRun #%s failed: %s", run.pk, found.reason)
    run.status = "failed"
    run.failure_cause = found.reason
    run.completed_at = found.stopped_at
    return run


def reconcile_abandoned_runs(
    runs: Iterable[AnalysisRun], *, now: datetime | None = None
) -> None:
    """Reconcile every run in *runs* in place, for readers rendering a list."""
    for run in runs:
        reconcile_abandoned_run(run, now=now)
