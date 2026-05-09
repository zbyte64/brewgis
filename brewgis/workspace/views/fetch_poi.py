"""View for importing OpenStreetMap Points of Interest."""

from __future__ import annotations

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.poi_fetcher import POI_CATEGORIES
from brewgis.workspace.tasks import run_poi_fetch


class POIFetchForm(forms.Form):
    """Form to configure a POI import from OpenStreetMap."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.label_class = "form-label"
        self.helper.field_class = "mb-3"

    workspace = forms.ModelChoiceField(
        queryset=Workspace.objects.all(),
        label="Workspace",
    )
    min_lng = forms.FloatField(
        label="West Longitude (min)",
        help_text="Western bound of bounding box (e.g., -121.5).",
    )
    min_lat = forms.FloatField(
        label="South Latitude (min)",
        help_text="Southern bound of bounding box (e.g., 38.4).",
    )
    max_lng = forms.FloatField(
        label="East Longitude (max)",
        help_text="Eastern bound of bounding box (e.g., -121.2).",
    )
    max_lat = forms.FloatField(
        label="North Latitude (max)",
        help_text="Northern bound of bounding box (e.g., 38.7).",
    )
    categories = forms.MultipleChoiceField(
        choices=sorted((k, k.replace("_", " ").title()) for k in POI_CATEGORIES),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="POI Categories",
        help_text="Select POI categories to import (default: all).",
    )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class POIFetchView(FormView):
    """View to import OpenStreetMap Points of Interest."""

    form_class = POIFetchForm
    template_name = "form.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Import Points of Interest"
        return context

    def form_valid(self, form: POIFetchForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]

        run = DataImportRun.objects.create(
            workspace=workspace,
            import_type="poi",
            params={
                "min_lng": data["min_lng"],
                "min_lat": data["min_lat"],
                "max_lng": data["max_lng"],
                "max_lat": data["max_lat"],
                "categories": data.get("categories", []),
            },
            status="pending",
        )

        run_poi_fetch.delay(
            run_pk=run.pk,
            min_lng=data["min_lng"],
            min_lat=data["min_lat"],
            max_lng=data["max_lng"],
            max_lat=data["max_lat"],
            categories=data.get("categories", []),
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

        return render(
            self.request,
            "workspace/import/status.html",
            {"run": run},
        )
