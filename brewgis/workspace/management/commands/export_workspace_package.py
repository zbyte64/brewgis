"""Export a workspace as a workspace package (``services.workspace_package``).

Usage::

    python manage.py export_workspace_package <workspace_pk> --output sacog.brewgis.zip
    python manage.py export_workspace_package <workspace_pk> --output sacog.brewgis.zip --include-public-data

The package carries the base layer, the Building Type library and the
workspace's own constraint layers / trip-length zones; ``--include-public-data``
adds its food outlets and road network so the importing server never fetches
them.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from brewgis.workspace.models import Workspace
from brewgis.workspace.services.workspace_package import PackageError
from brewgis.workspace.services.workspace_package import export_workspace_package


class Command(BaseCommand):
    help = "Export a workspace as a workspace package zip."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("workspace", type=int, help="Workspace primary key.")
        parser.add_argument("--output", required=True, help="Path of the zip to write.")
        parser.add_argument(
            "--include-public-data",
            action="store_true",
            help="Ship the workspace's food outlets and road network too.",
        )

    def handle(self, *args: object, **options: object) -> None:
        try:
            workspace = Workspace.objects.get(pk=options["workspace"])
        except Workspace.DoesNotExist:
            msg = f"Workspace {options['workspace']} does not exist."
            raise CommandError(msg) from None
        try:
            archive = export_workspace_package(
                workspace,
                include_public_data=bool(options["include_public_data"]),
                destination=Path(str(options["output"])).resolve(),
            )
        except PackageError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"Wrote {archive}"))
