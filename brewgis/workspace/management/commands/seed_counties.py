"""Management command — (re)seed the ``County`` FIPS lookup table.

``workspace_county`` is populated by the data migration
``0015_seed_county_fips``, which reads ``fixtures/county_fips.csv`` exactly
once. A migration never runs twice, so any later loss of those rows (a
database restore that drops public tables, a manual ``TRUNCATE``) leaves the
table empty forever — and ``WorkspaceCreateView`` cannot create a workspace
without at least one county to select.

Usage::

    python manage.py seed_counties
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from brewgis.workspace.models import County

if TYPE_CHECKING:
    from pathlib import Path

COUNTY_CSV: Path = settings.BASE_DIR / "workspace" / "fixtures" / "county_fips.csv"


class Command(BaseCommand):
    """Load the Census county FIPS reference rows into ``County``."""

    help = "Seed the County FIPS lookup table from fixtures/county_fips.csv"

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        if not COUNTY_CSV.exists():
            msg = f"County fixture not found at {COUNTY_CSV}"
            raise CommandError(msg)

        with COUNTY_CSV.open(newline="") as f:
            counties = [
                County(
                    state_fips=row["state_fips"],
                    county_fips=row["county_fips"],
                    name=row["name"],
                )
                for row in csv.DictReader(f)
            ]

        existing = County.objects.count()
        County.objects.bulk_create(counties, ignore_conflicts=True, batch_size=1000)
        inserted = County.objects.count() - existing

        self.stdout.write(
            self.style.SUCCESS(
                f"Counties: {inserted} inserted, {existing} already present"
            )
        )
