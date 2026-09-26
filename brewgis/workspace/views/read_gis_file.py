"""Upload a GIS file into a workspace's schema.

A file that already carries every base-canvas column is written at the types
the base-canvas contract needs (see ``base_canvas_dtypes``); anything else is
written as the file typed it.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

import geopandas
from crispy_forms.helper import FormHelper
from django import forms
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import Workspace
from brewgis.workspace.services._db import BigInteger
from brewgis.workspace.services._db import Float
from brewgis.workspace.services._db import Integer
from brewgis.workspace.services._db import Text
from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.views.built_forms import HtmxResponseMixin

if TYPE_CHECKING:
    from io import BufferedReader


class ImportGISFileForm(forms.Form):
    file = forms.FileField(required=True)
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    table_name = forms.CharField(max_length=63)

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

        # Validate file extension
        ext = os.path.splitext(file.name)[1].lower()
        allowed = settings.GIS_FILE_EXTENSIONS
        if ext not in allowed:
            # Also check for compound extensions like .shp.zip
            name_lower = file.name.lower()
            compound_match = any(
                name_lower.endswith(ae) for ae in allowed if "." in ae[1:]
            )
            if not compound_match:
                raise forms.ValidationError(
                    "Unsupported file type '%s'. Allowed: %s"
                    % (ext, ", ".join(allowed))
                )

        # Validate file size
        if file.size > settings.MAX_UPLOAD_SIZE:
            max_mb = settings.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise forms.ValidationError(
                "File too large (%.1f MB). Maximum: %.0f MB."
                % (file.size / (1024 * 1024), max_mb)
            )

        return cast("forms.FileField", file)


def _postgis_type(pg_type: str) -> Any:
    """Map a ``BaseCanvasSchema`` pg_type name to the type to declare on ingest."""
    upper = pg_type.upper()
    if "CHAR" in upper or "TEXT" in upper:
        return Text
    if "BIGINT" in upper or "SERIAL" in upper:
        return BigInteger
    if "INTEGER" in upper:
        return Integer
    return Float


def base_canvas_dtypes(frame: geopandas.GeoDataFrame) -> dict[str, Any]:
    """Column types to declare when *frame* is an uploaded base canvas.

    The base-canvas contract (every ``BaseCanvasSchema.COLUMN_NAMES`` column, at
    the types the canvas views need) is checked against the database, not the
    file — so a file that carries the right *columns* has to land with the right
    *types* or the table it produces is not adoptable at all. What a file's own
    typing is worth varies by format: GeoJSON has no column types, so a column
    that is empty in every row reads back as an object column and would land as
    ``text`` — in a column the paint surfaces COALESCE against a double
    precision value (see ``sqlmesh_tables._column_type_requirement``).

    Returns an empty mapping for a frame that is not base-canvas-shaped, leaving
    an ordinary upload's own typing untouched. ``geometry`` is deliberately left
    out: ``to_postgis`` writes that column's declaration itself, from the
    frame's CRS and geometry type.
    """
    required = set(BaseCanvasSchema.COLUMN_NAMES)
    if not required.issubset({str(column).lower() for column in frame.columns}):
        return {}

    dtypes: dict[str, Any] = {}
    for column in frame.columns:
        name = str(column).lower()
        if name == "geometry" or name not in required:
            continue
        column_def = BaseCanvasSchema.get(name)
        if column_def is not None:
            dtypes[column] = _postgis_type(column_def.pg_type)
    return dtypes


def read_gis_file_into_table(
    file_obj: BufferedReader, schema: str, table_name: str
) -> None:
    df = geopandas.read_file(file_obj)
    # columns need to be lower case for tipg: https://github.com/developmentseed/tipg/issues/195
    if settings.TILE_SERVER_BACKEND == "tipg":
        df.columns = map(str.lower, df.columns)
    con = get_engine()
    df.to_postgis(
        table_name, con, schema, chunksize=50000, dtype=base_canvas_dtypes(df)
    )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class ReadGISFileView(HtmxResponseMixin, FormView):
    form_class = ImportGISFileForm
    template_name = "form.html"

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        workspace_pk = self.request.GET.get("workspace")
        if workspace_pk:
            initial["workspace"] = workspace_pk
        return initial

    def form_valid(self, form: ImportGISFileForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]
        read_gis_file_into_table(
            file_obj=data["file"],
            schema=workspace.db_schema,
            table_name=data["table_name"],
        )
        redirect_url = reverse("workspace:workspace_map", args=[workspace.pk])
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)
