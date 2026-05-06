import os

import geopandas
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView
from sqlalchemy import create_engine

from brewgis.workspace.models import Workspace


class ImportGISFileForm(forms.Form):
    file = forms.FileField(required=True)
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    table_name = forms.CharField(max_length=63)


def read_gis_file_into_table(file_obj, schema: str, table_name: str):
    df = geopandas.read_file(file_obj)
    # columns need to be lower case for now: https://github.com/developmentseed/tipg/issues/195
    df.columns = map(str.lower, df.columns)
    con = create_engine(
        os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1),
    )
    df.to_postgis(table_name, con, schema, chunksize=50000)


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
        if self.request.htmx:
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: ImportGISFileForm) -> HttpResponse:
        if self.request.htmx:
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)
