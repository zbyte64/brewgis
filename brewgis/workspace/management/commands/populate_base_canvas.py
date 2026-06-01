"""Management command — populate ``public.base_canvas`` via the ETL pipeline.

Orchestrates the full ETL pipeline:

    1. Ensure base canvas table exists
    2. Load parcel features from source
    3. Compute area columns from geometry
    4. Allocate demographics (Census ACS -> parcels)
    5. Allocate employment (LEHD -> parcels)
    6. Estimate building areas
    7. Classify land use
    8. Estimate irrigation
    9. Compute intersection density
    10. Imputation pass
    11. Validate

Modes:
    ``--synthetic N``: generate *N* synthetic parcels for testing.
    ``--source-table``: read from an existing PostGIS parcel table.
    ``--source-geojson``: read from a GeoJSON file.
    ``--skip-imputation``: leave NULLs as-is (debugging).
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from brewgis.workspace.services.base_canvas_pipeline import run_pipeline

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Populate ``public.base_canvas`` from source parcel data."""

    help = "Populate the base canvas table via the ETL pipeline"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        source_group = parser.add_mutually_exclusive_group()
        source_group.add_argument(
            "--source-table",
            type=str,
            default=None,
            help="PostGIS table to read parcels from (schema.table)",
        )
        source_group.add_argument(
            "--source-geojson",
            type=str,
            default=None,
            help="GeoJSON file path to read parcels from",
        )
        source_group.add_argument(
            "--synthetic",
            type=int,
            default=None,
            help="Number of synthetic parcels to generate (for testing)",
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
            help="Truncate existing data before inserting",
        )
        parser.add_argument(
            "--target-table",
            type=str,
            default="public.base_canvas",
            help="Target table for ETL output (schema.table)",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, **options: str | int | bool | None) -> str | None:
        """Execute the ETL pipeline."""
        source_table: str | None = options.get("source_table")  # type: ignore[assignment]
        source_geojson: str | None = options.get("source_geojson")  # type: ignore[assignment]
        synthetic_n: int | None = options.get("synthetic")  # type: ignore[assignment]
        skip_imputation: bool = bool(options.get("skip_imputation", False))
        truncate: bool = bool(options.get("truncate", False))
        target_table: str = options.get("target_table", "public.base_canvas")  # type: ignore[assignment]

        try:
            result = run_pipeline(
                source_table=source_table,
                source_geojson=source_geojson,
                synthetic_n=synthetic_n,
                skip_imputation=skip_imputation,
                truncate=truncate,
                target_table=target_table,
            )
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        # Print messages
        for msg in result.get("messages", []):
            self.stdout.write(f"  {msg}")

        if result["status"] == "error":
            raise CommandError(result.get("error", "Unknown error"))

        self.stdout.write(
            self.style.SUCCESS(f"ETL pipeline complete in {result['elapsed']}s")
        )
        return None
