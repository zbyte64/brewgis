import os
import logging
from io import BufferedReader

import geopandas
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView
from sqlalchemy import create_engine

from brewgis.workspace.models import Workspace
from brewgis.workspace.services.column_inspector import inspect_table
from brewgis.workspace.services.staging_model import write_base_canvas_stub
from brewgis.workspace.services.staging_model import write_parcel_staging

logger = logging.getLogger(__name__)

class ImportGISFileForm(forms.Form):
    file = forms.FileField(required=True)
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    table_name = forms.CharField(max_length=63)


def read_gis_file_into_table(
    file_obj: BufferedReader, schema: str, table_name: str
) -> None:

    df = geopandas.read_file(file_obj)
    # columns need to be lower case for tipg: https://github.com/developmentseed/tipg/issues/195
    if settings.TILE_SERVER_BACKEND == "tipg":
        df.columns = map(str.lower, df.columns)
    con = create_engine(
        os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1),  # type: ignore[union-attr]
    )
    df.to_postgis(table_name, con, schema, chunksize=50000)
    # Phase 1c: generate dbt staging models for the imported table
    try:
        info = inspect_table(schema, table_name)
        if info is not None and info.id_column and info.has_geom:
            write_parcel_staging(schema, table_name, info)
            write_base_canvas_stub(schema, table_name, info)
            logger.info(
                "Generated staging models for %s.%s",
                schema,
                table_name,
            )
        else:
            logger.warning(
                "Skipping staging model generation for %s.%s: "
                "missing ID column or geometry",
                schema,
                table_name,
            )
    except Exception:
        logger.exception(
            "Failed to generate staging models for %s.%s",
            schema,
            table_name,
        )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class ReadGISFileView(FormView):
    form_class = ImportGISFileForm
    template_name = "form.html"

    def form_valid(self, form: ImportGISFileForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        read_gis_file_into_table(
            file_obj=data["file"],
            schema=workspace.db_schema,
            table_name=data["table_name"],
        )
        redirect_url = reverse("workspace:home")
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: ImportGISFileForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "form.html#form-content",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)
