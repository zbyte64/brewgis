"""Status polling view for data import runs."""
from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from brewgis.workspace.models import DataImportRun


@user_passes_test(lambda u: u.is_authenticated)
def import_status(request: HttpRequest, run_pk: int) -> HttpResponse:
    """htmx-polled status partial for a data import run."""
    run = get_object_or_404(DataImportRun, pk=run_pk)
    return render(
        request,
        "workspace/import/partials/_import_status.html",
        {"run": run},
    )
