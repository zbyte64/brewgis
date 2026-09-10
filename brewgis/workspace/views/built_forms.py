"""CRUD and baking views for BuildingTypes and PlaceTypes — workspace-scoped."""

from __future__ import annotations

from typing import Any

from crispy_forms.helper import FormHelper
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
from brewgis.workspace.models import Workspace

# ── HtmxResponseMixin ─────────────────────────────────────────────────


class HtmxResponseMixin:
    """Mixin providing htmx-aware form_valid, form_invalid, and delete handlers.

    Subclasses MUST define:
      - ``success_url_name`` (str): name for reverse() redirect on success
      - ``success_url_args`` (tuple): args for reverse(), default ()
    """

    success_url_name: str
    success_url_args: tuple = ()
    request: HttpRequest
    template_name: str

    def get_template_names(self) -> list[str]:
        """Render just the form fragment (no page chrome) for htmx panel loads.

        Panels are loaded via ``hx-get`` into ``#right-panel-content`` while
        the browser stays on the map page, so a full ``extends base.html``
        render would nest the whole page — nav bar included — inside the
        panel. Only htmx requests get the ``#form-content`` partial; a
        direct browser visit still gets the full page.
        """
        if getattr(self.request, "htmx", False):
            return [f"{self.template_name}#form-content"]
        return [self.template_name]

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=self.success_url_args)

    def get_success_url(self) -> str:
        """Override so Django's generic views redirect to our named URL."""
        return self.get_redirect_url()

    def form_valid(self, form: Any) -> HttpResponse:
        """Delegate actual work to parent, then intercept redirect for htmx."""
        response: HttpResponse = super().form_valid(form)  # type: ignore[misc]
        if getattr(self.request, "htmx", False):
            htmx_response = HttpResponse()
            htmx_response["HX-Redirect"] = self.get_redirect_url()
            return htmx_response
        return response

    def form_invalid(self, form: Any) -> HttpResponse:
        if getattr(self.request, "htmx", False):
            return render(
                self.request,
                self.get_template_names()[0],
                {"form": form, "view": self},
            )
        return super().form_invalid(form)  # type: ignore[misc, no-any-return]


# ── WorkspaceScopedMixin ──────────────────────────────────────────────


class WorkspaceScopedMixin:
    """Resolves ``self.workspace`` from the ``workspace_pk`` URL kwarg.

    BuildingTypes and PlaceTypes belong to exactly one workspace, so every
    CRUD view for them needs the workspace up front: to scope the queryset
    (an edit/delete can't reach another workspace's row), to stamp new rows
    on create, and to build the redirect back to that workspace's list.
    """

    kwargs: dict[str, Any]
    workspace: Workspace

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.workspace = get_object_or_404(Workspace, pk=kwargs["workspace_pk"])
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_queryset(self) -> Any:
        return super().get_queryset().filter(workspace=self.workspace)  # type: ignore[misc]

    def form_valid(self, form: Any) -> HttpResponse:
        form.instance.workspace = self.workspace
        return super().form_valid(form)  # type: ignore[misc, no-any-return]

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=[self.workspace.pk])  # type: ignore[attr-defined]


# ── ModelForms ──────────────────────────────────────────────────────────


class BuildingTypeForm(forms.ModelForm):
    """Form for creating/editing BuildingTypes."""

    class Meta:
        model = BuildingType
        fields = [
            "name",
            "description",
            "du_per_acre",
            "emp_per_acre",
            "far",
            "household_size",
            "tenure_owner_pct",
            "tenure_renter_pct",
            "vacancy_rate",
            "stories",
            "footprint_per_unit",
            "building_coverage",
            "jobs_by_sector",
            "indoor_water_rate",
            "outdoor_water_rate",
            "irrigable_area_fraction",
            "electricity_eui",
            "gas_eui",
            "vintage",
            "parking_spaces_per_unit",
            "parking_spaces_per_1000sqft",
            "parking_sqft_per_space",
            "ite_land_use_code",
            "trip_rate_override",
            "pass_by_trip_pct",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "jobs_by_sector": forms.Textarea(
                attrs={"rows": 3, "placeholder": '{"retail": 40, "office": 60}'},
            ),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False


class PlaceTypeForm(forms.ModelForm):
    """Form for creating/editing PlaceTypes."""

    class Meta:
        model = PlaceType
        fields = [
            "name",
            "description",
            "row_allocation_pct",
            "block_size",
            "street_pattern",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False


# ── Building Type CRUD ──────────────────────────────────────────────────


auth_method = user_passes_test(lambda u: u.is_authenticated)


@method_decorator(auth_method, name="dispatch")
class BuildingTypeCreateView(WorkspaceScopedMixin, HtmxResponseMixin, CreateView):
    """Create a new BuildingType in a workspace."""

    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:building_type_list"


@method_decorator(auth_method, name="dispatch")
class BuildingTypeUpdateView(WorkspaceScopedMixin, HtmxResponseMixin, UpdateView):
    """Edit an existing BuildingType."""

    model = BuildingType
    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:building_type_list"


@method_decorator(auth_method, name="dispatch")
class BuildingTypeDeleteView(WorkspaceScopedMixin, HtmxResponseMixin, DeleteView):  # type: ignore[misc]
    """Delete a BuildingType."""

    model = BuildingType
    success_url_name = "workspace:building_type_list"


# ── Place Type CRUD ─────────────────────────────────────────────────────


@method_decorator(auth_method, name="dispatch")
class PlaceTypeCreateView(WorkspaceScopedMixin, HtmxResponseMixin, CreateView):
    """Create a new PlaceType in a workspace."""

    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:place_type_list"


@method_decorator(auth_method, name="dispatch")
class PlaceTypeUpdateView(WorkspaceScopedMixin, HtmxResponseMixin, UpdateView):
    """Edit an existing PlaceType."""

    model = PlaceType
    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:place_type_list"


@method_decorator(auth_method, name="dispatch")
class PlaceTypeDeleteView(WorkspaceScopedMixin, HtmxResponseMixin, DeleteView):  # type: ignore[misc]
    """Delete a PlaceType."""

    model = PlaceType
    success_url_name = "workspace:place_type_list"


# ── List Views ──────────────────────────────────────────────────────────


@user_passes_test(lambda u: u.is_authenticated)
def building_type_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """List a workspace's BuildingTypes."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    building_types = BuildingType.objects.filter(workspace=workspace)
    return render(
        request,
        "workspace/built_forms/building_type_list.html",
        {"workspace": workspace, "building_types": building_types},
    )


@user_passes_test(lambda u: u.is_authenticated)
def place_type_list(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """List a workspace's PlaceTypes."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    place_types = PlaceType.objects.filter(workspace=workspace)
    return render(
        request,
        "workspace/built_forms/place_type_list.html",
        {"workspace": workspace, "place_types": place_types},
    )


# ── Baking Views ────────────────────────────────────────────────────────


def building_type_bake(
    request: HttpRequest, workspace_pk: int, pk: int
) -> HttpResponse:
    """Show bake form (GET) or run allocation (POST) for a BuildingType."""
    building_type = get_object_or_404(BuildingType, pk=pk, workspace_id=workspace_pk)

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
        "workspace/built_forms/building_type_bake.html#bake-results",
        {
            "result": result,
            "built_form_name": building_type.name,
            "built_form_type": "building_type",
            "acres": acres,
            "row_pct": row_pct,
        },
    )


def place_type_bake(request: HttpRequest, workspace_pk: int, pk: int) -> HttpResponse:
    """Show bake form (GET) or run allocation (POST) for a PlaceType."""
    place_type = get_object_or_404(
        PlaceType.objects.prefetch_related(
            "building_type_mixes__building_type",
        ),
        pk=pk,
        workspace_id=workspace_pk,
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
        "workspace/built_forms/place_type_bake.html#bake-results",
        {
            "result": result,
            "built_form_name": place_type.name,
            "built_form_type": "place_type",
            "acres": acres,
            "row_pct": place_type.row_allocation_pct or 25.0,
        },
    )
