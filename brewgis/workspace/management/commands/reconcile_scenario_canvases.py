"""Re-materialize scenario canvas views that a plan left missing or stale."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from brewgis.workspace.services.scenario_canvas import reconcile_scenario_canvases


class Command(BaseCommand):
    help = (
        "Recreate any ALTERNATIVE scenario's canvas view that is missing or no "
        "longer resolves (see brewgis.workspace.services.scenario_canvas)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        unhealthy = reconcile_scenario_canvases()
        if unhealthy:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reconciled scenario canvas views (unhealthy before: {unhealthy})"
                )
            )
            return
        self.stdout.write("Reconciled scenario canvas views (all were healthy).")
