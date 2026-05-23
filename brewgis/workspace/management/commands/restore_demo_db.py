"""Restore the UrbanFootprint SACOG demo database from .sql.gz dump.

Delegates to :func:`brewgis.workspace.services.sacog_demo_db.restore_sacog_demo_db`.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from brewgis.workspace.services.sacog_demo_db import RestoreError
from brewgis.workspace.services.sacog_demo_db import restore_sacog_demo_db


class Command(BaseCommand):
    help = "Restore the UrbanFootprint SACOG demo database from .sql.gz dump"

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            restore_sacog_demo_db(log=self.stdout)
        except RestoreError as e:
            raise CommandError(str(e)) from e

        self.stdout.write(self.style.SUCCESS("Demo database restored successfully"))
