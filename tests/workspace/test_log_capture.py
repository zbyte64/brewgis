# ruff: noqa: ANN201
"""Tests for the SQLMesh failure helpers — scraping the log and describing the
exception chain."""

from __future__ import annotations

import logging
import logging.config
import threading

from celery.exceptions import SoftTimeLimitExceeded
from sqlglot.errors import SchemaError
from sqlmesh.utils.errors import ConfigError

from brewgis.workspace.analysis.log_capture import capture_run_log
from brewgis.workspace.analysis.log_capture import describe_run_failure
from brewgis.workspace.analysis.log_capture import extract_plan_failure
from brewgis.workspace.analysis.log_capture import truncate_log

logger = logging.getLogger("brewgis.test_log_capture")

# Verbatim shape of what SQLMesh's scheduler writes when a plan node fails:
# the record message is the generic node error and ``exc_info`` appends the
# chained traceback whose innermost exception is the database's own error.
_NODE_FAILURE = (
    "Execution failed for node EvaluateNode("
    'snapshot_name=\'"brewgis"."analysis"."core_end_state"\', '
    "interval=(1704067200000, 1789948800000), batch_index=0)"
)
PLAN_FAILURE_LOG = "\n".join(
    [
        "INFO 2026-09-21 20:33:40,428 sqlmesh.core.console some console warning",
        'INFO 2026-09-21 20:33:52,055 sqlmesh.core.scheduler SKIPPED snapshot "brewgis"."analysis"."vmt"',
        f"INFO 2026-09-21 20:33:52,055 sqlmesh.core.scheduler {_NODE_FAILURE}",
        "Traceback (most recent call last):",
        '  File "/usr/.../sqlmesh/utils/concurrency.py", line 69, in _process_node',
        "    self.fn(node)",
        '  File "/usr/.../sqlmesh/core/scheduler.py", line 554, in run_node',
        "    audit_results = self.evaluate(",
        '  File "/usr/.../sqlmesh/core/engine_adapter/base.py", line 2664, in _execute',
        "    self.cursor.execute(sql, **kwargs)",
        'psycopg2.errors.UndefinedTable: relation "scenario_default.scenario_default_canvas" does not exist',
        'LINE 1: ..."emp_per_acre" > 0 AS "is_nonresidential" FROM "brewgis"....',
        "                                                             ^",
        "",
        "The above exception was the direct cause of the following exception:",
        "",
        "Traceback (most recent call last):",
        '  File "/usr/.../sqlmesh/utils/concurrency.py", line 62, in _process_node',
        "    self.fn(node)",
        "sqlmesh.utils.concurrency.NodeExecutionFailedError: " + _NODE_FAILURE,
        "INFO 2026-09-21 20:33:53,907 sqlmesh.core.context Plan application failed.",
        "",
    ]
)


class TestCaptureRunLog:
    """Unit tests for the capture_run_log context manager."""

    def test_captures_info_and_above(self):
        with capture_run_log() as stream:
            logger.info("hello from the plan")
            logger.warning("a warning")
        output = stream.getvalue()
        assert "hello from the plan" in output
        assert "a warning" in output

    def test_does_not_capture_debug(self):
        with capture_run_log() as stream:
            logger.debug("should not appear")
        assert "should not appear" not in stream.getvalue()

    def test_handler_removed_after_block(self):
        root = logging.getLogger()
        before = len(root.handlers)
        with capture_run_log():
            assert len(root.handlers) == before + 1
        assert len(root.handlers) == before

    def test_ignores_records_from_other_threads(self):
        """Only the thread that entered the block should be captured —
        otherwise concurrent requests/tasks in the same process would leak
        each other's log output into an unrelated AnalysisRun."""
        with capture_run_log() as stream:
            other_thread_logged = threading.Event()

            def _log_from_other_thread():
                logger.info("from another thread")
                other_thread_logged.set()

            t = threading.Thread(target=_log_from_other_thread)
            t.start()
            t.join()
            assert other_thread_logged.is_set()

        assert "from another thread" not in stream.getvalue()

    def test_captures_exceptions_logged_via_logger_exception(self):
        with capture_run_log() as stream:
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("something failed")
        output = stream.getvalue()
        assert "something failed" in output
        assert "ValueError: boom" in output

    def test_survives_root_logger_reconfiguration(self):
        """Capturing must outlive a ``logging.config.dictConfig`` re-run.

        Django re-applies its LOGGING setting through dictConfig on every
        ``django.setup()`` call, and SQLMesh calls that mid-plan when it
        imports the project's Python models. dictConfig strips every handler
        off the loggers it configures, so a root-only capture handler died a
        few lines into each plan — leaving a failed run's stored log output
        with startup noise instead of the per-node error.
        """
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level
        try:
            with capture_run_log() as stream:
                logger.info("before reconfigure")
                logging.config.dictConfig(
                    {
                        "version": 1,
                        "disable_existing_loggers": False,
                        "handlers": {"null": {"class": "logging.NullHandler"}},
                        "root": {"level": "INFO", "handlers": ["null"]},
                    }
                )
                logger.info("after reconfigure")
        finally:
            root.handlers[:] = saved_handlers
            root.setLevel(saved_level)

        output = stream.getvalue()
        assert "before reconfigure" in output
        assert "after reconfigure" in output

    def test_records_are_not_duplicated_across_attached_loggers(self):
        """The handler sits on several loggers so that dictConfig can't take
        the last copy with it; a record must still be written exactly once."""
        with capture_run_log() as stream:
            logger.info("exactly once")
        assert stream.getvalue().count("exactly once") == 1


class TestExtractPlanFailure:
    """Tests for recovering the real cause out of a captured plan log."""

    def test_recovers_failing_model_and_database_error(self):
        failure = extract_plan_failure(PLAN_FAILURE_LOG)
        assert failure is not None
        assert failure.model == "brewgis.analysis.core_end_state"
        assert "psycopg2.errors.UndefinedTable" in failure.detail
        assert 'relation "scenario_default.scenario_default_canvas" does not exist' in (
            failure.detail
        )
        # The database's own context lines are what make the message actionable.
        assert "LINE 1:" in failure.detail

    def test_format_leads_with_the_model(self):
        failure = extract_plan_failure(PLAN_FAILURE_LOG)
        assert failure is not None
        summary = failure.format()
        assert summary.startswith("brewgis.analysis.core_end_state — ")
        assert "UndefinedTable" in summary

    def test_returns_none_without_a_node_failure(self):
        assert extract_plan_failure("") is None
        assert (
            extract_plan_failure("INFO 2026-09-21 20:33:40,428 base Executing SQL:")
            is None
        )


class TestDescribeRunFailure:
    """Cause for a failure that never reached a plan node.

    A run that dies while SQLMesh renders the project logs no per-node record,
    so ``extract_plan_failure`` finds nothing and the run's own exception chain
    is the only description left.
    """

    def test_names_the_model_and_macro_of_a_render_failure(self):
        """Verbatim shape of run 67: the task's soft time limit landed inside a
        macro while SQLMesh was rendering a model to load the project."""
        config_error = ConfigError(
            "Failed to resolve macros for\n\nSELECT 1\n\n"
            "An error occurred during evaluation of 'arcgis_page_urls'\n"
            " at '/app/brewgis/sqlmesh/models/fresno/assessor_parcels_duckdb.sql'"
        )
        config_error.__cause__ = SoftTimeLimitExceeded()
        schema_error = SchemaError("Failed to update model schemas")
        schema_error.__cause__ = config_error

        # The model is named as the project declares it (assessor_parcels_duckdb
        # is the model duckdb.fresno.assessor_parcels), and the macro names the
        # call site the file alone can't.
        assert describe_run_failure(schema_error) == (
            "duckdb.fresno.assessor_parcels — macro 'arcgis_page_urls': "
            "task killed by the Celery soft time limit before it finished"
        )

    def test_falls_back_to_the_innermost_exception(self):
        outer = RuntimeError("plan blew up")
        outer.__cause__ = ValueError('column "x" does not exist')

        assert describe_run_failure(outer) == 'ValueError: column "x" does not exist'

    def test_describes_a_bare_soft_time_limit(self):
        assert describe_run_failure(SoftTimeLimitExceeded()) == (
            "task killed by the Celery soft time limit before it finished"
        )


class TestTruncateLog:
    """Unit tests for truncate_log."""

    def test_short_text_unchanged(self):
        assert truncate_log("hello", max_chars=100) == "hello"

    def test_long_text_truncated_keeping_tail(self):
        text = "x" * 50 + "END"
        result = truncate_log(text, max_chars=10)
        assert result.endswith(text[-10:])
        assert result.endswith("END")
        assert "truncated" in result
        assert len(result) < len(text)
