"""View for uploading a GeoTIFF raster file and extracting its metadata."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from typing import cast

from crispy_forms.helper import FormHelper
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.tasks import run_raster_fetch
from brewgis.workspace.views.built_forms import HtmxResponseMixin

_RASTER_EXTENSIONS = (".tif", ".tiff", ".geotiff")
_UPLOAD_DIR = Path("/app/planning/raster_uploads")


class RasterUploadForm(forms.Form):
    """Form to upload a GeoTIFF for metadata/band-statistics extraction."""

    file = forms.FileField(required=True, label="GeoTIFF file")
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False
        workspace_pk = self.initial.get("workspace")
        if workspace_pk:
            self.fields["workspace"].queryset = Workspace.objects.filter(
                pk=workspace_pk,
            )
            self.fields["workspace"].widget = forms.HiddenInput()

    def clean_file(self) -> forms.FileField | None:
        file = self.cleaned_data.get("file")
        if file is None:
            return file

        ext = Path(file.name).suffix.lower()
        if ext not in _RASTER_EXTENSIONS:
            msg = f"Unsupported file type '{ext}'. Allowed: {', '.join(_RASTER_EXTENSIONS)}"
            raise forms.ValidationError(msg)

        if file.size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            msg = f"File too large ({file.size / (1024 * 1024):.1f} MB). Maximum: {max_mb:.0f} MB."
            raise forms.ValidationError(msg)

        return cast("forms.FileField", file)


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class RasterUploadView(HtmxResponseMixin, FormView):
    """Upload a GeoTIFF; dispatches a Celery task to extract its metadata."""

    form_class = RasterUploadForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    extra_context = {"title": "Upload Raster"}

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        workspace_pk = self.request.GET.get("workspace")
        if workspace_pk:
            initial["workspace"] = workspace_pk
        return initial

    def form_valid(self, form: RasterUploadForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        uploaded = data["file"]

        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(uploaded.name).suffix.lower()
        file_path = str(_UPLOAD_DIR / f"{uuid.uuid4()}{ext}")
        with Path(file_path).open("wb") as dest:
            dest.writelines(uploaded.chunks())

        run = DataImportRun.objects.create(
            workspace=workspace,
            import_type="raster",
            params={"file_path": file_path, "original_name": uploaded.name},
            status="pending",
        )
        run_raster_fetch.delay(
            run_pk=run.pk,
            file_path=file_path,
            schema=workspace.db_schema,
        )

        if self.request.htmx:  # type: ignore[attr-defined]
            html = render_to_string(
                "workspace/import/status.html#import-status",
                {"run": run},
                request=self.request,
            )
            response = HttpResponse(html)
            response["HX-Trigger"] = "import-started"
            return response

        return render(self.request, "workspace/import/status.html", {"run": run})
