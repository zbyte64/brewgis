# ruff: noqa: ARG002, PLC0415, S608
"""Django management command to run Soda Core data quality validation.

Usage::

    python manage.py validate_data_quality                    # all contracts
    python manage.py validate_data_quality --contract base_canvas  # single
    python manage.py validate_data_quality --contract *_canvas  # glob
    python manage.py validate_data_quality --list              # list available
"""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Validate data quality using Soda Core."""

    help = "Run Soda Core data quality contracts."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--contract",
            default=None,
            help="Contract name or glob pattern (e.g. 'base_canvas', '*_canvas').",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_contracts",
            default=False,
            help="List available contracts and exit.",
        )

    def handle(self, *args: Any, **options: Any) -> str:
        soda_dir = Path(
            getattr(settings, "SODA_PROJECT_DIR", settings.APPS_DIR / "soda")
        )
        contracts_dir = soda_dir / "contracts"
        all_contracts = sorted(
            p.stem for p in contracts_dir.glob("*.yml") if p.stem != "dbt_module_run"
        )

        if options["list_contracts"]:
            self._list_contracts(all_contracts)
            return ""

        if options["contract"]:
            selected = self._resolve_contracts(all_contracts, options["contract"])
        else:
            selected = all_contracts

        if not selected:
            msg = "No contracts matched the given criteria."
            raise CommandError(msg)

        return self._run_selected(selected)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _list_contracts(self, names: list[str]) -> None:
        """Print a list of available contracts."""
        self.stdout.write(self.style.MIGRATE_HEADING("Available contracts:"))
        for name in sorted(names):
            self.stdout.write(f"  {name}")

    def _resolve_contracts(self, all_names: list[str], pattern: str) -> list[str]:
        """Resolve a name or glob pattern to a list of contract names."""
        if pattern in all_names:
            return [pattern]
        matched = fnmatch.filter(all_names, pattern)
        if not matched:
            msg = (
                f"No contracts match pattern '{pattern}'. Use --list to see available."
            )
            raise CommandError(msg)
        return matched

    def _run_selected(self, names: list[str]) -> str:
        """Run selected contracts and report results."""
        from brewgis.soda import run_scan

        all_ok = True
        for name in names:
            self.stdout.write(f"\n── {name} ──")
            self._ensure_table(name)
            result = run_scan(name)
            self._report_result(name, result)
            if not result["success"]:
                all_ok = False

        if all_ok:
            self.stdout.write(self.style.SUCCESS("\nAll contracts passed."))
            return ""
        msg = "Some contracts failed."
        raise CommandError(msg)

    def _ensure_table(self, name: str) -> None:
        """Seed data for contracts whose tables are produced by ETL pipelines.

        Each target table is created on first call (idempotent — skips if
        the table already exists).
        """
        if name == "built_form_export":
            _seed_built_form_export()
        _seed_remaining_contracts()

    def _report_result(self, name: str, result: dict[str, Any]) -> None:
        """Print a human-readable result summary."""
        status = (
            self.style.SUCCESS("PASS")
            if result["success"]
            else self.style.ERROR("FAIL")
        )
        self.stdout.write(f"  {status}")
        if not result["success"]:
            for failure in result.get("failures", []):
                self.stdout.write(f"    - {failure}")


def _seed_built_form_export() -> None:
    """Seed ``built_forms`` from Django BuildingType records."""
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.workspace_buildingtype")
        (count,) = cursor.fetchone()
    if count == 0:
        fixture_path = (
            settings.APPS_DIR
            / "workspace"
            / "built_forms"
            / "fixtures"
            / "default_library.json"
        )
        call_command("loaddata", str(fixture_path), format="json")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'built_forms')"
        )
        if cursor.fetchone()[0]:
            return

    from brewgis.workspace.analysis.data_export import _NULLABLE_TO_ZERO
    from brewgis.workspace.analysis.data_export import BUILT_FORM_COLUMNS

    col_parts: list[str] = []
    for out_name, source_expr in BUILT_FORM_COLUMNS.items():
        if out_name in _NULLABLE_TO_ZERO:
            col_parts.append(f"COALESCE({source_expr}, 0.0) AS {out_name}")
        else:
            col_parts.append(f"{source_expr} AS {out_name}")
    cols = ",\n            ".join(col_parts)

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS public.built_forms AS
            SELECT {cols}
            FROM public.workspace_buildingtype
            WITH NO DATA
            """
        )
        cursor.execute("TRUNCATE TABLE public.built_forms")
        cursor.execute(
            f"""
            INSERT INTO public.built_forms
            SELECT {cols}
            FROM public.workspace_buildingtype
            """
        )


def _seed_remaining_contracts() -> None:
    """Seed ETL pipeline staging/output tables used by Soda contracts."""
    from brewgis.soda.seed import seed_all

    seed_all()
