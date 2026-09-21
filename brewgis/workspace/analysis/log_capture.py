"""Captures Python logging output produced while running a SQLMesh plan.

SQLMesh reports plan progress, warnings, and per-node failures through
Python's ``logging`` module when it isn't attached to an interactive
terminal (as in a Celery worker or a web request) — its own top-level
exception (``PlanError("Plan application failed.")``) discards the actual
cause. Capturing this is the only way to recover *why* a plan failed.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import threading
from typing import TYPE_CHECKING
from typing import NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

# Keep stored logs bounded — a verbose plan across many models can log
# thousands of lines, and the failure (if any) is always near the end, so
# truncating from the front loses the least useful part.
MAX_LOG_CHARS = 200_000

# Loggers the capture handler is attached to.
#
# Attaching to the root logger alone is not enough. Django applies its
# ``LOGGING`` setting through ``logging.config.dictConfig``, and dictConfig
# removes *every* handler from each logger it configures — root included.
# SQLMesh triggers exactly that in the middle of a plan: ``Context.load()``
# imports the project's Python models, one of which calls ``django.setup()``,
# and ``django.setup()`` re-applies the LOGGING config on every call. A
# root-only handler therefore dies a few lines into every plan, which is how
# a failed AnalysisRun's ``log_output`` ended up holding two startup lines
# instead of the per-node error.
#
# dictConfig only touches loggers named in the config, so handlers attached
# to the ``sqlmesh`` and ``brewgis`` namespaces survive it; records logged
# under those namespaces still arrive through normal propagation.
_CAPTURE_LOGGER_NAMES = ("", "sqlmesh", "brewgis")

# Detail lines kept from the underlying exception's traceback — enough for
# the database's own context (``LINE 1: ...`` plus its caret) without
# dragging the whole traceback into the summary.
_MAX_DETAIL_LINES = 4
_TRACEBACK_HEADER = "Traceback (most recent call last):"
# Continuation lines of one log record are unformatted, so a new record
# starts exactly where the handler's formatter would have written a prefix.
_RECORD_PREFIX = re.compile(
    r"^(?:DEBUG|INFO|WARNING|ERROR|CRITICAL) \d{4}-\d{2}-\d{2} "
)
# An exception line sits at column 0; traceback frames are indented, and
# PostgreSQL's own ``LINE 1:`` context does not match this shape.
_EXCEPTION_LINE = re.compile(r"^([A-Za-z_][\w.]*): (.+)$")
_SNAPSHOT_NAME = re.compile(r"snapshot_name='([^']+)'")


class _ThreadScopedHandler(logging.Handler):
    """Captures records from only the thread that created this handler.

    Root-logger handlers otherwise see every record from every thread —
    fine for a Celery prefork worker (one task per process) but unsafe if
    this is ever entered from a multi-threaded web worker running other
    requests concurrently.
    """

    def __init__(self, stream: io.StringIO) -> None:
        super().__init__(level=logging.INFO)
        self._stream = stream
        self._thread_id = threading.get_ident()
        # This handler is attached to several loggers at once (see
        # _CAPTURE_LOGGER_NAMES), so the same record reaches it once per
        # ancestor logger. Mark the record instead of writing it out again;
        # the marker is per-handler so concurrently-capturing handlers
        # don't suppress each other.
        self._marker = f"_brewgis_capture_{id(self)}"
        self.setFormatter(
            logging.Formatter("%(levelname)s %(asctime)s %(name)s %(message)s")
        )

    def filter(self, record: logging.LogRecord) -> bool:
        return record.thread == self._thread_id

    def emit(self, record: logging.LogRecord) -> None:
        if hasattr(record, self._marker):
            return
        setattr(record, self._marker, True)
        with contextlib.suppress(Exception):
            self._stream.write(self.format(record) + "\n")


@contextlib.contextmanager
def capture_run_log() -> Iterator[io.StringIO]:
    """Capture INFO+ log records emitted (by this thread) inside the block.

    Yields the underlying buffer; read it after the block exits (or at any
    point inside it, for progressive capture) via ``.getvalue()``.
    """
    stream = io.StringIO()
    handler = _ThreadScopedHandler(stream)
    loggers = [logging.getLogger(name) for name in _CAPTURE_LOGGER_NAMES]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        yield stream
    finally:
        for logger in loggers:
            logger.removeHandler(handler)


def truncate_log(text: str, max_chars: int = MAX_LOG_CHARS) -> str:
    """Trim *text* to its last *max_chars*, noting that it was truncated."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"... [{omitted} earlier characters truncated] ...\n" + text[-max_chars:]


class PlanFailure(NamedTuple):
    """The per-node failure SQLMesh logs and then discards.

    Recovered from captured log output because SQLMesh's own
    ``PlanError("Plan application failed.")`` carries no cause: the
    scheduler logs each failed node at INFO (with the real exception chained
    as ``__cause__``) and the plan evaluator only raises the generic error.
    """

    model: str
    """Failing model FQN, e.g. ``brewgis.analysis.core_end_state``."""

    node: str
    """Full node description, e.g. ``EvaluateNode(snapshot_name=..., ...)``."""

    detail: str
    """Underlying exception line plus the database's own context lines."""

    def format(self) -> str:
        """Render as the one block worth showing a user."""
        if self.model and self.detail:
            return f"{self.model} — {self.detail}"
        return self.detail or self.model or self.node


def _split_records(text: str) -> list[list[str]]:
    """Group formatted log lines back into records with their tracebacks."""
    records: list[list[str]] = []
    for line in text.splitlines():
        if _RECORD_PREFIX.match(line) or not records:
            records.append([line])
        else:
            records[-1].append(line)
    return records


def _detail_from_record(record: list[str]) -> str:
    """Pull the underlying exception (and its context) out of one record."""
    body = record[1:]
    try:
        start = body.index(_TRACEBACK_HEADER)
    except ValueError:
        return ""
    for offset, line in enumerate(body[start:], start=start):
        if _EXCEPTION_LINE.match(line):
            detail: list[str] = []
            for follow in body[offset : offset + _MAX_DETAIL_LINES]:
                if not follow.strip() or follow.startswith(_TRACEBACK_HEADER):
                    break
                detail.append(follow)
            return "\n".join(detail)
    return ""


def _model_from_node(node: str) -> str:
    """Extract the model FQN from a node description, if it carries one."""
    match = _SNAPSHOT_NAME.search(node)
    return match.group(1).replace('"', "") if match else ""


def extract_plan_failure(log_text: str) -> PlanFailure | None:
    """Recover the first per-node failure recorded in *log_text*.

    Returns ``None`` when the captured output holds no node failure — the
    caller then has only SQLMesh's generic ``PlanError`` to show.
    """
    if not log_text:
        return None
    for record in _split_records(log_text):
        if "Execution failed for node " not in record[0]:
            continue
        node = record[0].split("Execution failed for node ", 1)[1].strip()
        return PlanFailure(
            model=_model_from_node(node),
            node=node,
            detail=_detail_from_record(record),
        )
    return None
