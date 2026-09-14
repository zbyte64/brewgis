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
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Keep stored logs bounded — a verbose plan across many models can log
# thousands of lines, and the failure (if any) is always near the end, so
# truncating from the front loses the least useful part.
MAX_LOG_CHARS = 200_000


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
        self.setFormatter(
            logging.Formatter("%(levelname)s %(asctime)s %(name)s %(message)s")
        )

    def filter(self, record: logging.LogRecord) -> bool:
        return record.thread == self._thread_id

    def emit(self, record: logging.LogRecord) -> None:
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
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        yield stream
    finally:
        root_logger.removeHandler(handler)


def truncate_log(text: str, max_chars: int = MAX_LOG_CHARS) -> str:
    """Trim *text* to its last *max_chars*, noting that it was truncated."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"... [{omitted} earlier characters truncated] ...\n" + text[-max_chars:]
