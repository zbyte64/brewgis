"""Captures Python logging output produced while running a SQLMesh plan.

SQLMesh reports plan progress, warnings, and per-node failures through
Python's ``logging`` module when it isn't attached to an interactive
terminal (as in a Celery worker or a web request) — its own top-level
exception (``PlanError("Plan application failed.")``) discards the actual
cause. Capturing this is the only way to recover *why* a plan failed.

A run can also die *before* the plan, while SQLMesh renders the project —
``Context.load()`` renders every model, so a macro that raises, or a task
that hits its time limit mid-render, fails the run with no plan node behind
it and therefore nothing in the log to scrape: ``describe_run_failure``
recovers a cause from the exception chain instead.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from typing import NamedTuple

from celery.exceptions import SoftTimeLimitExceeded

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

# SQLMesh's ConfigError ends with the model file it failed on, the same
# location its CLI prints — e.g. "... at '/app/brewgis/sqlmesh/models/
# fresno/assessor_parcels_duckdb.sql'".
_MODEL_LOCATION = re.compile(r"at '[^']*sqlmesh/models/(?P<rel>[\w/.-]+\.sql)'")
# The model's own name, as declared in its MODEL DDL (``name a.b.c,``).
_MODEL_DDL_NAME = re.compile(r"\bname\s+(?P<name>[A-Za-z_][\w.]*)\s*,", re.MULTILINE)
# A render failure names the macro that raised, which the model file alone
# doesn't identify (``arcgis_page_urls`` is called from several models).
_MACRO_EVALUATION = re.compile(
    r"An error occurred during evaluation of '(?P<macro>[^']+)'"
)
# Guard against a self-referential exception chain.
_MAX_EXCEPTION_CHAIN = 20


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


_MODELS_DIR = Path(__file__).resolve().parents[2] / "sqlmesh" / "models"
"""The project's model tree — resolves the bare file name from the message."""


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """*exc*, then whatever it was raised from, outermost first.

    ``Context.load()`` wraps a render failure several layers deep
    (``SchemaError`` around SQLMesh's ``ConfigError`` around the macro's own
    ``MacroEvalError`` around the exception that actually stopped it), and the
    model file only appears in the middle of that chain.
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while (
        current is not None
        and id(current) not in seen
        and len(chain) < _MAX_EXCEPTION_CHAIN
    ):
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _declared_model_name(rel_path: str) -> str:
    """The name a project model file declares in its MODEL DDL, if any.

    The file name alone is ambiguous (``assessor_parcels_duckdb.sql`` is the
    model ``duckdb.fresno.assessor_parcels``); the declared name is what the
    lineage view, the audits and the database call it.
    """
    try:
        text = (_MODELS_DIR / rel_path).read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _MODEL_DDL_NAME.search(text)
    return match.group("name") if match else ""


def _describe_exception(exc: BaseException) -> str:
    """One readable line for the innermost exception of a chain."""
    if isinstance(exc, SoftTimeLimitExceeded):
        return "task killed by the Celery soft time limit before it finished"
    message = " ".join(str(exc).split())
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message[:200]}"


def describe_run_failure(exc: BaseException) -> str:
    """One-line cause for a failure that never reached a plan node.

    A run that dies while SQLMesh renders the project — a macro raising, or the
    task's time limit landing mid-render — logs no per-node record for
    :func:`extract_plan_failure` to find, and SQLMesh's own exception names
    neither the model in a form a reader can act on nor the reason underneath
    it. Its chain does carry both: the model file SQLMesh appends to a
    ``ConfigError`` (``... at '<path>'``), the macro that raised when one did,
    and the innermost exception.

    Returns the innermost exception alone when the chain names no model, so the
    result is never empty.
    """
    model = ""
    macro = ""
    chain = _exception_chain(exc)
    for candidate in chain:
        text = str(candidate)
        if not model:
            match = _MODEL_LOCATION.search(text)
            if match:
                model = _declared_model_name(match.group("rel")) or match.group("rel")
        if not macro:
            match = _MACRO_EVALUATION.search(text)
            if match:
                macro = match.group("macro")
        if model and macro:
            break

    detail = _describe_exception(chain[-1])
    if macro:
        detail = f"macro '{macro}': {detail}"
    return f"{model} — {detail}" if model else detail
