"""Workspace package export and import (``services.workspace_package``).

Export lives on the workspace hub: a ``WorkspaceExport`` row is created and the
package is written by a Celery task, its status partial polled until the zip is
ready to download. Import lives in the Import Center: the upload is validated
and unpacked into a new workspace in the request (a refused package never
creates one), and the base canvas is built by a Celery task tracked by a
``package`` ``DataImportRun``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from brewgis.workspace.models import LOCAL_SRID_HELP_TEXT
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import WorkspaceExport
from brewgis.workspace.models import validate_projected_srid
from brewgis.workspace.services.workspace_package import PackageError
from brewgis.workspace.services.workspace_package import import_workspace_package
from brewgis.workspace.tasks import export_workspace_package_task
from brewgis.workspace.tasks import start_package_build
from brewgis.workspace.views.built_forms import HtmxResponseMixin

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile
    from django.http import HttpRequest


class WorkspaceExportForm(forms.Form):
    include_public_data = forms.BooleanField(
        required=False,
        label="Include food outlets and road network",
        help_text=(
            "Ship the workspace's public data so the importing server never fetches "
            "it (a larger package). Without it, the importer fetches them over the "
            "workspace extent the first time an analysis needs them."
        ),
    )


def _export_status(request: HttpRequest, export: WorkspaceExport) -> HttpResponse:
    return render(
        request,
        "workspace/workspace_package/export_status.html#export-status",
        {"export": export, "workspace": export.workspace},
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def workspace_export_create(request: HttpRequest, pk: int) -> HttpResponse:
    """Start exporting the workspace as a package."""
    workspace = get_object_or_404(Workspace, pk=pk)
    form = WorkspaceExportForm(request.POST)
    form.is_valid()
    export = WorkspaceExport.objects.create(
        workspace=workspace,
        include_public_data=bool(form.cleaned_data.get("include_public_data")),
        created_by=request.user if request.user.is_authenticated else None,
    )
    transaction.on_commit(lambda: export_workspace_package_task.delay(export.pk))
    if getattr(request, "htmx", False):
        return _export_status(request, export)
    return redirect("workspace:workspace_detail", pk=pk)


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def workspace_export_status(
    request: HttpRequest, pk: int, export_pk: int
) -> HttpResponse:
    """htmx-polled status partial for one export."""
    export = get_object_or_404(WorkspaceExport, pk=export_pk, workspace_id=pk)
    return _export_status(request, export)


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def workspace_export_download(
    request: HttpRequest, pk: int, export_pk: int
) -> FileResponse:
    """Download a finished export's package."""
    export = get_object_or_404(WorkspaceExport, pk=export_pk, workspace_id=pk)
    name = export.file.name
    if export.status != WorkspaceExport.Status.COMPLETED or not name:
        msg = "This export has no package to download."
        raise Http404(msg)
    return FileResponse(
        export.file.open("rb"),
        as_attachment=True,
        filename=Path(name).name,
        content_type="application/zip",
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def workspace_export_delete(
    request: HttpRequest, pk: int, export_pk: int
) -> HttpResponse:
    """Delete an export and its package file."""
    export = get_object_or_404(WorkspaceExport, pk=export_pk, workspace_id=pk)
    export.delete()
    if getattr(request, "htmx", False):
        return HttpResponse("")
    return redirect("workspace:workspace_detail", pk=pk)


@user_passes_test(lambda u: u.is_authenticated)
@require_POST
def workspace_package_rebuild(request: HttpRequest, pk: int) -> HttpResponse:
    """Build an imported workspace's packaged base canvas again (after a failed build)."""
    workspace = get_object_or_404(Workspace, pk=pk)
    if not workspace.package_dir:
        msg = "This workspace was not imported from a package."
        raise Http404(msg)
    start_package_build(workspace, params={"retry": True})
    return redirect("workspace:workspace_detail", pk=pk)


class ImportWorkspacePackageForm(forms.Form):
    package = forms.FileField(
        label="Workspace package (.zip)",
        help_text="A package exported from a BrewGIS workspace.",
    )
    name = forms.CharField(
        max_length=128,
        required=False,
        help_text="Name of the new workspace (default: the package's).",
    )
    local_srid = forms.IntegerField(
        required=False,
        label="Projected CRS (EPSG code)",
        validators=[validate_projected_srid],
        help_text=f"{LOCAL_SRID_HELP_TEXT} Default: the package's.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False

    def clean_package(self) -> UploadedFile:
        package = self.cleaned_data["package"]
        if not package.name.lower().endswith(".zip"):
            msg = "A workspace package is a .zip file."
            raise forms.ValidationError(msg)
        if package.size > settings.MAX_WORKSPACE_PACKAGE_SIZE:
            limit = settings.MAX_WORKSPACE_PACKAGE_SIZE / (1024 * 1024)
            msg = f"Package too large (limit {limit:.0f} MB)."
            raise forms.ValidationError(msg)
        return package


def _uploaded_path(upload: UploadedFile, directory: Path) -> Path:
    """A filesystem path holding *upload* (the zip reader needs to seek)."""
    path = directory / "package.zip"
    with path.open("wb") as handle:
        for chunk in upload.chunks():
            handle.write(chunk)
    return path


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class ImportWorkspacePackageView(HtmxResponseMixin, FormView):
    """Import a workspace package as a new workspace."""

    form_class = ImportWorkspacePackageForm
    template_name = "form.html"
    extra_context = {"title": "Import Workspace Package"}
    workspace: Workspace

    def get_redirect_url(self) -> str:
        return reverse("workspace:workspace_detail", kwargs={"pk": self.workspace.pk})

    def form_valid(self, form: ImportWorkspacePackageForm) -> HttpResponse:
        data = form.cleaned_data
        with tempfile.TemporaryDirectory(prefix="brewgis-upload-") as tmp:
            try:
                self.workspace = import_workspace_package(
                    _uploaded_path(data["package"], Path(tmp)),
                    name=data["name"] or None,
                    local_srid=data["local_srid"],
                )
            except PackageError as error:
                form.add_error("package", str(error))
                return self.form_invalid(form)
        start_package_build(self.workspace, params={"package": data["package"].name})
        return super().form_valid(form)
