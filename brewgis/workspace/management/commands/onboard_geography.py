"""Management command — onboarding for a new geography.

Single entry point that creates a :class:`~brewgis.workspace.models.Workspace`
and :class:`~brewgis.workspace.models.Scenario`, then runs the full base
canvas ETL pipeline with real Census/LEHD data sources.

Usage::

    python manage.py onboard_geography \\
        --name "Fresno County" \\
        --parcels /data/fresno_parcels.geojson \\
        --state-fips 06 \\
        --county-fips 019

Optional::

    --skip-imputation    Leave NULL values as-is.
    --truncate           Truncate existing base canvas before writing.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from brewgis.workspace.services.base_canvas_pipeline import run_pipeline

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Onboard a new geography — workspace + base canvas ETL."""

    help = "Create a workspace and populate the base canvas for a new geography"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Human-readable name for the geography (e.g. 'Fresno County')",
        )
        parser.add_argument(
            "--parcels",
            type=str,
            required=True,
            help="Path to GeoJSON file containing parcel geometries",
        )
        parser.add_argument(
            "--state-fips",
            type=str,
            required=True,
            help="Two-digit state FIPS code (e.g. '06' for California)",
        )
        parser.add_argument(
            "--county-fips",
            type=str,
            required=True,
            help="Three-digit county FIPS code (e.g. '019' for Fresno)",
        )
        parser.add_argument(
            "--skip-imputation",
            action="store_true",
            default=False,
            help="Skip the imputation pass (leave NULLs as-is)",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            default=False,
            help="Truncate existing base canvas data before inserting",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, **options: str | int | bool | None) -> str | None:
        """Execute onboarding workflow."""
        name: str = str(options.get("name", ""))
        parcels_path: str = str(options.get("parcels", ""))

        skip_imputation: bool = bool(options.get("skip_imputation", False))
        truncate: bool = bool(options.get("truncate", False))

        self.stdout.write(f"=== Onboarding Geography: {name} ===\n")

        # ── Run ETL ─────────────────────────────────────────────────
        self.stdout.write("Running base canvas ETL pipeline ...")
        result = run_pipeline(
            source_geojson=parcels_path,
            skip_imputation=skip_imputation,
            truncate=truncate,
        )

        for msg in result.get("messages", []):
            self.stdout.write(f"  {msg}")

        if result["status"] == "error":
            raise CommandError(result.get("error", "Unknown ETL error"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nETL pipeline complete: {result['rows']} rows in {result['elapsed']}s"
            )
        )

        # ── Print summary ───────────────────────────────────────────
        self._print_summary()

        return None

    def _print_summary(self) -> None:
        """Print a summary of the base canvas contents."""

        from django.db import connection as db_conn
        from django.db import transaction

        # Check if table exists without risking broken transaction
        with db_conn.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'base_canvas')"
            )
            if not cursor.fetchone()[0]:
                self.stdout.write("\n  (Table does not exist)")
                return

        try:
            with transaction.atomic(), db_conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
                row_count = cursor.fetchone()[0]
                self.stdout.write(f"\n  Rows: {row_count}")
        except Exception:
            self.stdout.write("\n  (Table query failed - no data?)")
            return

        with db_conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(pop), 0) FROM public.base_canvas")
            pop_total = cursor.fetchone()[0]
            self.stdout.write(f"  Population: {pop_total:,.0f}")

        with db_conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(hh), 0) FROM public.base_canvas")
            hh_total = cursor.fetchone()[0]
            self.stdout.write(f"  Households: {hh_total:,.0f}")

        with db_conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(emp), 0) FROM public.base_canvas")
            emp_total = cursor.fetchone()[0]
            self.stdout.write(f"  Employment: {emp_total:,.0f}")

        with db_conn.cursor() as cursor:
            cursor.execute(
                "SELECT land_development_category, COUNT(*) "
                "FROM public.base_canvas GROUP BY land_development_category "
                "ORDER BY COUNT(*) DESC"
            )
            rows = cursor.fetchall()
            if rows:
                self.stdout.write("  Land Use:")
                for cat, cnt in rows:
                    self.stdout.write(f"    {cat}: {cnt}")
