"""Model signals that publish map events (see ``services/map_events.py``).

Layers are created, deleted, regrouped and restyled from many places: views,
import and analysis tasks, the filter service, MCP tools and management
commands. Hooking the models catches every one of them and tells open map
pages to reconcile their layer list. Background runs (paint, analysis, import)
announce each status change the same way, whichever code path saved it.

Wired in ``WorkspaceConfig.ready``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from brewgis.workspace.models import WORKSPACE_PACKAGES_DIR
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerGroup
from brewgis.workspace.models import PaintRun
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import WorkspaceExport
from brewgis.workspace.services.map_events import notify_map


@receiver(post_save, sender=Layer)
@receiver(post_delete, sender=Layer)
@receiver(post_save, sender=LayerGroup)
@receiver(post_delete, sender=LayerGroup)
def _layer_changed(instance: Layer | LayerGroup, **_: object) -> None:
    notify_map(workspace_id=instance.workspace_id, kind="layers.changed")


@receiver(post_save, sender=SymbologyConfig)
@receiver(post_delete, sender=SymbologyConfig)
def _symbology_changed(instance: SymbologyConfig, **_: object) -> None:
    workspace_id = (
        Layer.objects.filter(pk=instance.layer_id)
        .values_list("workspace_id", flat=True)
        .first()
    )
    if workspace_id is not None:
        notify_map(workspace_id=workspace_id, kind="layers.changed")


def _status_saved(update_fields: frozenset[str] | None) -> bool:
    return update_fields is None or "status" in update_fields


@receiver(post_save, sender=PaintRun)
def _paint_run_saved(
    instance: PaintRun, update_fields: frozenset[str] | None, **_: object
) -> None:
    if not _status_saved(update_fields):
        return
    result = instance.result or {}
    notify_map(
        workspace_id=instance.workspace_id,
        kind="paint.run",
        run_pk=instance.pk,
        scenario_id=instance.scenario_id,
        status=instance.status,
        error=instance.error_log
        or (result.get("message", "") if result.get("status") == "error" else ""),
    )


@receiver(post_save, sender=AnalysisRun)
def _analysis_run_saved(
    instance: AnalysisRun, update_fields: frozenset[str] | None, **_: object
) -> None:
    if not _status_saved(update_fields):
        return
    notify_map(
        workspace_id=instance.workspace_id,
        kind="analysis.run",
        run_pk=instance.pk,
        scenario_id=instance.scenario_id,
        modules=list(instance.modules or []),
        status=instance.status,
    )
    if instance.status == "completed":
        # A run rewrites the result tables behind already-registered layers.
        notify_map(workspace_id=instance.workspace_id, kind="tiles.changed")


@receiver(post_save, sender=DataImportRun)
def _import_run_saved(
    instance: DataImportRun, update_fields: frozenset[str] | None, **_: object
) -> None:
    if not _status_saved(update_fields):
        return
    notify_map(
        workspace_id=instance.workspace_id,
        kind="import.run",
        run_pk=instance.pk,
        import_type=instance.import_type,
        status=instance.status,
    )


# ── Files a row owns ──────────────────────────────────────────────────
# Not map events: the files on disk that belong to a row, removed once the
# deletion has committed (a rolled-back delete keeps them).


@receiver(post_delete, sender=Workspace)
def _workspace_deleted(instance: Workspace, **_: object) -> None:
    root = Path(settings.MEDIA_ROOT) / WORKSPACE_PACKAGES_DIR / str(instance.pk)
    schema = instance.input_schema

    def cleanup() -> None:
        # Imported lazily: the SQLMesh runner is not app start-up's to load.
        from brewgis.workspace.analysis.sqlmesh_runner import (
            purge_models_from_environments,
        )

        shutil.rmtree(root, ignore_errors=True)
        # Its ``wsp<pk>`` input models leave the project with the row; a stale
        # environment entry would fail the next plan that promotes it (the
        # reason ``drop_scenario_analysis`` de-lists a scenario's models).
        purge_models_from_environments(schemas=[schema])

    transaction.on_commit(cleanup)


@receiver(post_delete, sender=WorkspaceExport)
def _export_deleted(instance: WorkspaceExport, **_: object) -> None:
    name = instance.file.name
    if name:
        storage = instance.file.storage
        transaction.on_commit(lambda: storage.delete(name))
