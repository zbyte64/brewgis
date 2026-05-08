"""View for importing LEHD employment data."""
from __future__ import annotations

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.workspace.models import DataImportRun
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.lehd_fetcher import fetch_lehd_data_summary
from brewgis.workspace.tasks import run_lehd_fetch


class EmploymentFetchForm(forms.Form):
    """Form to configure a LEHD employment data import."""
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
    state_fips = forms.CharField(
        max_length=2,
        label="State FIPS Code",
        help_text="Two-digit state FIPS code.",
    )
    county_fips = forms.CharField(
        max_length=3,
        label="County FIPS Code",
        help_text="Three-digit county FIPS code.",
    )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class EmploymentFetchView(FormView):
    """View to import LEHD employment data."""

    form_class = EmploymentFetchForm
    template_name = "form.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Import LEHD Employment"
        return context

    def form_valid(self, form: EmploymentFetchForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]

        run = DataImportRun.objects.create(
            workspace=workspace,
            import_type="lehd",
            params={
                "state_fips": data["state_fips"],
                "county_fips": data["county_fips"],
            },
            status="pending",
        )

        run_lehd_fetch.delay(
            run_pk=run.pk,
            state_fips=data["state_fips"],
            county_fips=data["county_fips"],
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


def employment_preview(request: HttpRequest) -> HttpResponse:
    """htmx partial showing preview of available LEHD data."""
    state_fips = request.GET.get("state_fips", "")
    county_fips = request.GET.get("county_fips", "")
    summary = {}

    if state_fips and county_fips:
        summary = fetch_lehd_data_summary(state_fips, county_fips)

    return render(
        request,
        "workspace/import_center.html#employment-preview",
        {"summary": summary},
    )
