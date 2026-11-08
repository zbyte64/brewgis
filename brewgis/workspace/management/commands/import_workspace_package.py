"""Import a workspace package as a new workspace (``services.workspace_package``).

Usage::

    python manage.py import_workspace_package sacog.brewgis.zip
    python manage.py import_workspace_package sacog.brewgis.zip --name "SACOG (imported)" --local-srid 26910

Creates the workspace (its Building Types and a base scenario) and builds its
base canvas in this process, so the workspace is ready to paint and analyze when
the command returns.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from brewgis.workspace.services.workspace_package import PackageError
from brewgis.workspace.services.workspace_package import build_package_base
from brewgis.workspace.services.workspace_package import import_workspace_package


class Command(BaseCommand):
    help = "Import a workspace package zip as a new workspace."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("package", help="Path of the workspace package zip.")
        parser.add_argument("--name", help="Workspace name (default: the package's).")
        parser.add_argument(
            "--local-srid",
            type=int,
            help="Projected CRS to analyze in (default: the package's).",
        )

    def handle(self, *args: object, **options: object) -> None:
        path = Path(str(options["package"])).resolve()
        if not path.is_file():
            msg = f"{path} does not exist."
            raise CommandError(msg)
        try:
            workspace = import_workspace_package(
                path,
                name=options["name"] or None,  # type: ignore[arg-type]
                local_srid=options["local_srid"],  # type: ignore[arg-type]
            )
        except PackageError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"Created workspace {workspace.pk} ({workspace.name}); building its base canvas…"
        )
        build_package_base(workspace)
        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace {workspace.pk} is ready: base table {workspace.base_table}"
            )
        )
