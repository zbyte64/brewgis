"""CRUD and baking views for BuildingTypes and PlaceTypes."""
from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
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
class BuildingTypeCreateView(CreateView):
    """Create a new BuildingType."""

    form_class = BuildingTypeForm
    template_name = "form.html"

    def form_valid(self, form: BuildingTypeForm) -> HttpResponse:
        self.object = form.save()
        redirect_url = reverse("workspace:building_type_list")
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: BuildingTypeForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)


@method_decorator(auth_method, name="dispatch")
class BuildingTypeUpdateView(UpdateView):
    """Edit an existing BuildingType."""

    model = BuildingType
    form_class = BuildingTypeForm
    template_name = "form.html"

    def get_object(self, **_kwargs: Any) -> BuildingType:
        return get_object_or_404(BuildingType, pk=self.kwargs["pk"])

    def form_valid(self, form: BuildingTypeForm) -> HttpResponse:
        self.object = form.save()
        redirect_url = reverse("workspace:building_type_list")
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: BuildingTypeForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)


@method_decorator(auth_method, name="dispatch")
class BuildingTypeDeleteView(DeleteView):
    """Delete a BuildingType."""

    model = BuildingType

    def get_success_url(self) -> str:
        return reverse("workspace:building_type_list")

    def delete(self, request: HttpRequest, *_args: Any, **_kwargs: Any) -> HttpResponse:
            self.object = self.get_object()


# ── Place Type CRUD ─────────────────────────────────────────────────────


@method_decorator(auth_method, name="dispatch")
class PlaceTypeCreateView(CreateView):
    """Create a new PlaceType."""

    form_class = PlaceTypeForm
    template_name = "form.html"

    def form_valid(self, form: PlaceTypeForm) -> HttpResponse:
        self.object = form.save()
        redirect_url = reverse("workspace:place_type_list")
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: PlaceTypeForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)


@method_decorator(auth_method, name="dispatch")
class PlaceTypeUpdateView(UpdateView):
    """Edit an existing PlaceType."""

    model = PlaceType
    form_class = PlaceTypeForm
    template_name = "form.html"

    def get_object(self, **_kwargs: Any) -> PlaceType:
        return get_object_or_404(PlaceType, pk=self.kwargs["pk"])

    def form_valid(self, form: PlaceTypeForm) -> HttpResponse:
        self.object = form.save()
        redirect_url = reverse("workspace:place_type_list")
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: PlaceTypeForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)


@method_decorator(auth_method, name="dispatch")
class PlaceTypeDeleteView(DeleteView):
    """Delete a PlaceType."""

    model = PlaceType

    def get_success_url(self) -> str:
        return reverse("workspace:place_type_list")

    def delete(self, request: HttpRequest, *_args: Any, **_kwargs: Any) -> HttpResponse:
        self.object = self.get_object()
        self.object.delete()
        redirect_url = self.get_success_url()
        if request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

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
# Aliases for URL imports
building_type_create = BuildingTypeCreateView  # noqa: F811
building_type_edit = BuildingTypeUpdateView  # noqa: F811
building_type_delete = BuildingTypeDeleteView  # noqa: F811
place_type_create = PlaceTypeCreateView  # noqa: F811
place_type_edit = PlaceTypeUpdateView  # noqa: F811
place_type_delete = PlaceTypeDeleteView  # noqa: F811
