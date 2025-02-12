from ..models import Workspace
import geopandas
import os
import pandas
from sqlalchemy import create_engine

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django import forms
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView


class ImportGISFileForm(forms.Form):
    file = forms.FileField(required=True)
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    table_name = forms.CharField(max_length=63)


def read_gis_file_into_table(file_obj, schema: str, table_name: str):
    df = geopandas.read_file(file_obj)
    # columns need to be lower case for now: https://github.com/developmentseed/tipg/issues/195
    df.columns = map(str.lower, df.columns)
    con = create_engine(os.environ.get('DATABASE_URL').replace("postgres://", "postgresql://", 1))
    df.to_postgis(table_name, con, schema, chunksize=50000)


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class ReadGISFileView(FormView):
    form_class = ImportGISFileForm
    template_name = "form.html"

    def form_valid(self, form: ImportGISFileForm):
        data = form.cleaned_data
        workspace: Workspace = data['workspace']
        read_gis_file_into_table(
            file_obj=data['file'], 
            schema=workspace.db_schema, 
            table_name=data['table_name']
        )
        return 'ok'
        # TODO return a response

