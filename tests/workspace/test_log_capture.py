# ruff: noqa: ANN201
"""Tests for capture_run_log/truncate_log — the SQLMesh log-scraping helper."""

from __future__ import annotations

import logging
import threading

from brewgis.workspace.analysis.log_capture import capture_run_log
from brewgis.workspace.analysis.log_capture import truncate_log

logger = logging.getLogger("brewgis.test_log_capture")


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
