"""CRUD and baking views for BuildingTypes and PlaceTypes."""
from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import CreateView
from django.views.generic.edit import DeleteView
from django.views.generic.edit import UpdateView

from brewgis.workspace.built_forms.allocation import AllocationEngine
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType

# ── HtmxResponseMixin ─────────────────────────────────────────────────


class HtmxResponseMixin:
    """Mixin providing htmx-aware form_valid, form_invalid, and delete handlers.

    Subclasses MUST define:
      - ``success_url_name`` (str): name for reverse() redirect on success
      - ``success_url_args`` (tuple): args for reverse(), default ()
    """

    success_url_name: str
    success_url_args: tuple = ()

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=self.success_url_args)

    def get_success_url(self) -> str:
        """Override so Django's generic views redirect to our named URL."""
        return self.get_redirect_url()

    def form_valid(self, form: Any) -> HttpResponse:
        """Delegate actual work to parent, then intercept redirect for htmx."""
        response = super().form_valid(form)
        if getattr(self.request, "htmx", False):
            htmx_response = HttpResponse()
            htmx_response["HX-Redirect"] = self.get_redirect_url()
            return htmx_response
        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        if getattr(self.request, "htmx", False):
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)


# ── ModelForms ──────────────────────────────────────────────────────────


class BuildingTypeForm(forms.ModelForm):
    """Form for creating/editing BuildingTypes."""

    class Meta:
        model = BuildingType
        fields = [
            "name", "description",
            "du_per_acre", "emp_per_acre", "far",
            "household_size", "tenure_owner_pct", "tenure_renter_pct", "vacancy_rate",
            "stories", "footprint_per_unit", "building_coverage",
            "jobs_by_sector",
            "indoor_water_rate", "outdoor_water_rate", "irrigable_area_fraction",
            "electricity_eui", "gas_eui", "vintage",
            "parking_spaces_per_unit", "parking_spaces_per_1000sqft", "parking_sqft_per_space",
            "ite_land_use_code", "trip_rate_override", "pass_by_trip_pct",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "jobs_by_sector": forms.Textarea(
                attrs={"rows": 3, "placeholder": '{"retail": 40, "office": 60}'},
            ),
        }


class PlaceTypeForm(forms.ModelForm):
    """Form for creating/editing PlaceTypes."""

    class Meta:
        model = PlaceType
        fields = [
            "name", "description",
            "row_allocation_pct",
            "block_size", "street_pattern",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


# ── Building Type CRUD ──────────────────────────────────────────────────


auth_method = user_passes_test(lambda u: u.is_authenticated)


@method_decorator(auth_method, name="dispatch")
class BuildingTypeCreateView(HtmxResponseMixin, CreateView):
    """Create a new BuildingType."""

    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:building_type_list"


@method_decorator(auth_method, name="dispatch")
class BuildingTypeUpdateView(HtmxResponseMixin, UpdateView):
    """Edit an existing BuildingType."""

    model = BuildingType
    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:building_type_list"


@method_decorator(auth_method, name="dispatch")
class BuildingTypeDeleteView(HtmxResponseMixin, DeleteView):
    """Delete a BuildingType."""

    model = BuildingType
    success_url_name = "workspace:building_type_list"


# ── Place Type CRUD ─────────────────────────────────────────────────────


@method_decorator(auth_method, name="dispatch")
class PlaceTypeCreateView(HtmxResponseMixin, CreateView):
    """Create a new PlaceType."""

    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:place_type_list"


@method_decorator(auth_method, name="dispatch")
class PlaceTypeUpdateView(HtmxResponseMixin, UpdateView):
    """Edit an existing PlaceType."""

    model = PlaceType
    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:place_type_list"


@method_decorator(auth_method, name="dispatch")
class PlaceTypeDeleteView(HtmxResponseMixin, DeleteView):
    """Delete a PlaceType."""

    model = PlaceType
    success_url_name = "workspace:place_type_list"


# ── List Views ──────────────────────────────────────────────────────────


@user_passes_test(lambda u: u.is_authenticated)
def building_type_list(request: HttpRequest) -> HttpResponse:
    """List all BuildingTypes."""
    building_types = BuildingType.objects.all()
    return render(
        request,
        "workspace/built_forms/building_type_list.html",
        {"building_types": building_types},
    )


@user_passes_test(lambda u: u.is_authenticated)
def place_type_list(request: HttpRequest) -> HttpResponse:
    """List all PlaceTypes."""
    place_types = PlaceType.objects.all()
    return render(
        request,
        "workspace/built_forms/place_type_list.html",
        {"place_types": place_types},
    )


# ── Baking Views ────────────────────────────────────────────────────────


def building_type_bake(request: HttpRequest, pk: int) -> HttpResponse:
    """Show bake form (GET) or run allocation (POST) for a BuildingType."""
    building_type = get_object_or_404(BuildingType, pk=pk)

    if request.method == "GET":
        return render(
            request,
            "workspace/built_forms/building_type_bake.html",
            {"building_type": building_type},
        )

    try:
        acres = float(request.POST.get("acres", 10.0))
    except (ValueError, TypeError):
        acres = 10.0

    row_pct = float(request.POST.get("row_pct", 25.0))
    result = AllocationEngine.allocation_building_type(
        parcel_acres=acres,
        building_type=building_type,
        row_allocation_pct=row_pct,
    )

    return render(
        request,
        "workspace/built_forms/partials/_bake_results.html",
        {
            "result": result,
            "built_form_name": building_type.name,
            "built_form_type": "building_type",
            "acres": acres,
            "row_pct": row_pct,
        },
    )


def place_type_bake(request: HttpRequest, pk: int) -> HttpResponse:
    """Show bake form (GET) or run allocation (POST) for a PlaceType."""
    place_type = get_object_or_404(
        PlaceType.objects.prefetch_related(
            "building_type_mixes__building_type",
        ),
        pk=pk,
    )

    if request.method == "GET":
        return render(
            request,
            "workspace/built_forms/place_type_bake.html",
            {"place_type": place_type},
        )

    try:
        acres = float(request.POST.get("acres", 40.0))
    except (ValueError, TypeError):
        acres = 40.0

    result = AllocationEngine.allocation_place_type(
        parcel_acres=acres,
        place_type=place_type,
    )

    return render(
        request,
        "workspace/built_forms/partials/_bake_results.html",
        {
            "result": result,
            "built_form_name": place_type.name,
            "built_form_type": "place_type",
            "acres": acres,
            "row_pct": place_type.row_allocation_pct or 25.0,
        },
    )
