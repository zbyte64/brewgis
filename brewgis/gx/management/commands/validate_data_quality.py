# ruff: noqa: ARG002, PLC0415
"""Django management command to run Great Expectations data quality validation.

Usage::

    python manage.py validate_data_quality                    # all checkpoints
    python manage.py validate_data_quality --checkpoint base_canvas_etl  # single
    python manage.py validate_data_quality --checkpoint dbt_*  # glob
    python manage.py validate_data_quality --list              # list available
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Validate data quality using Great Expectations."""

    help = "Run Great Expectations data quality checkpoints."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--checkpoint",
            default=None,
            help="Checkpoint name or glob pattern (e.g. 'base_canvas_*').",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_checkpoints",
            default=False,
            help="List available checkpoints and exit.",
        )

    def handle(self, *args: Any, **options: Any) -> str:
        # Lazy import so GX availability doesn't block manage.py startup.
        from brewgis.gx import get_gx_context

        context = get_gx_context()
        all_checkpoints = context.list_checkpoints()

        if options["list_checkpoints"]:
            self._list_checkpoints(all_checkpoints, context)
            return ""

        if options["checkpoint"]:
            selected = self._resolve_checkpoints(all_checkpoints, options["checkpoint"])
        else:
            selected = all_checkpoints


        if not selected:
            msg = "No checkpoints matched the given criteria."
            raise CommandError(msg)

        return self._run_selected(selected, context)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _list_checkpoints(self, names: list[str], context: Any) -> None:
        """Print a list of available checkpoints."""
        self.stdout.write(self.style.MIGRATE_HEADING("Available checkpoints:"))
        for name in sorted(names):
            self.stdout.write(f"  {name}")

    def _resolve_checkpoints(self, all_names: list[str], pattern: str) -> list[str]:
        """Resolve a name or glob pattern to a list of checkpoint names."""
        if pattern in all_names:
            return [pattern]
        matched = fnmatch.filter(all_names, pattern)
        if not matched:
            msg = f"No checkpoints match pattern '{pattern}'. Use --list to see available."
            raise CommandError(msg)
        return matched


    def _run_selected(self, names: list[str], context: Any) -> str:
        """Run selected checkpoints and report results."""
        all_ok = True
        for cp_name in names:
            self.stdout.write(f"\n── {cp_name} ──")
            try:
                checkpoint = context.checkpoints[cp_name]
                result = checkpoint.run()
                self._report_result(cp_name, result)
                if not result.success:
                    all_ok = False
            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"  ERROR: {e}"))
                all_ok = False

        if all_ok:
            self.stdout.write(self.style.SUCCESS("\nAll checkpoints passed."))
            return ""
        msg = "Some checkpoints failed."
        raise CommandError(msg)

    def _report_result(self, name: str, result: Any) -> None:
        """Print a human-readable result summary."""
        status = self.style.SUCCESS("PASS") if result.success else self.style.ERROR("FAIL")
        self.stdout.write(f"  {status}")
        if not result.success:
            for run_result in result.run_results.values():
                for suite_result in run_result.get("validation_results", []):
                    for exp in suite_result.get("results", []):
                        if not exp.get("success", True):
                            ec = exp.get("expectation_config", {})
                            self.stdout.write(
                                f"    - {ec.get('expectation_type', 'unknown')}: "
                                f"{ec.get('kwargs', {})}"
                            )
