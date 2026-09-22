"""Re-publish scenario analysis result views a plan left missing or stale."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from brewgis.workspace.services.scenario_analysis import modeled_scenario_ids
from brewgis.workspace.services.scenario_analysis import reconcile_scenario_analyses


class Command(BaseCommand):
    help = (
        "Restate every analyzed scenario's analysis models so their result "
        "views are recreated over the models' current prod virtual views (see "
        "brewgis.workspace.services.scenario_analysis)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        scenarios = len(modeled_scenario_ids())
        reconcile_scenario_analyses()
        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciled analysis result views for {scenarios} scenario(s)."
            )
        )
