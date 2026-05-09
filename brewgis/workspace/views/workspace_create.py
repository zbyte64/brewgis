"""View for creating a new Workspace."""

from __future__ import annotations

from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.generic.edit import FormView

from brewgis.workspace.models import County
from brewgis.workspace.models import Workspace

US_STATES: list[tuple[str, str]] = [
    ("01", "Alabama"),
    ("02", "Alaska"),
    ("04", "Arizona"),
    ("05", "Arkansas"),
    ("06", "California"),
    ("08", "Colorado"),
    ("09", "Connecticut"),
    ("10", "Delaware"),
    ("11", "District of Columbia"),
    ("12", "Florida"),
    ("13", "Georgia"),
    ("15", "Hawaii"),
    ("16", "Idaho"),
    ("17", "Illinois"),
    ("18", "Indiana"),
    ("19", "Iowa"),
    ("20", "Kansas"),
    ("21", "Kentucky"),
    ("22", "Louisiana"),
    ("23", "Maine"),
    ("24", "Maryland"),
    ("25", "Massachusetts"),
    ("26", "Michigan"),
    ("27", "Minnesota"),
    ("28", "Mississippi"),
    ("29", "Missouri"),
    ("30", "Montana"),
    ("31", "Nebraska"),
    ("32", "Nevada"),
    ("33", "New Hampshire"),
    ("34", "New Jersey"),
    ("35", "New Mexico"),
    ("36", "New York"),
    ("37", "North Carolina"),
    ("38", "North Dakota"),
    ("39", "Ohio"),
    ("40", "Oklahoma"),
    ("41", "Oregon"),
    ("42", "Pennsylvania"),
    ("44", "Rhode Island"),
    ("45", "South Carolina"),
    ("46", "South Dakota"),
    ("47", "Tennessee"),
    ("48", "Texas"),
    ("49", "Utah"),
    ("50", "Vermont"),
    ("51", "Virginia"),
    ("53", "Washington"),
    ("54", "West Virginia"),
    ("55", "Wisconsin"),
    ("56", "Wyoming"),
]


class WorkspaceCreateForm(forms.Form):
    """Form for creating a new workspace."""

    name = forms.CharField(max_length=128, required=True)
    description = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class WorkspaceCreateView(FormView):
    """Create a new Workspace."""

    form_class = WorkspaceCreateForm
    template_name = "workspace/workspace_form.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["US_STATES"] = US_STATES
        state = self.request.GET.get("state")
        if state:
            context["counties"] = County.objects.filter(
                state_fips=state,
            ).order_by("county_fips")
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        name = form.cleaned_data["name"]
        state_fips = self.request.POST.get("state_fips", "")
        county_fips_values = self.request.POST.getlist("county_fips")
        if not county_fips_values:
            form.add_error(None, "Please select at least one county.")
            return self.render_to_response(self.get_context_data(form=form))
        county_fips = [{"state": state_fips, "county": c} for c in county_fips_values]
        workspace = Workspace.objects.create(
            name=name,
            db_schema=slugify(name),
            county_fips_list=county_fips,
        )
        return redirect(
            reverse("workspace:workspace_detail", kwargs={"pk": workspace.pk})
        )


@user_passes_test(lambda u: u.is_authenticated)
def county_options(request: HttpRequest) -> HttpResponse:
    """Return rendered county checkboxes for a given state FIPS code."""
    state = request.GET["state"]
    counties = County.objects.filter(state_fips=state).order_by("county_fips")
    return render(
        request,
        "workspace/partials/_county_checkboxes.html",
        {"counties": counties},
    )
