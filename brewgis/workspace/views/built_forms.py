"""Create/edit/delete views for BuildingTypes and PlaceTypes.

The built-form library has no page of its own: it is the map shell's
"Built Forms" left-sidebar panel (``views.panels.panel_built_forms``). That
panel lists the workspace's types, opens these create/edit forms in the map's
right-hand drawer, and POSTs deletes back here — the same shape as the layer
list and the symbology editor, so managing the library never navigates away
from the map. Every mutation therefore answers with the htmx protocol instead
of a page: a saved form re-renders itself with a ``built-forms-changed`` event,
a delete swaps nothing and lets that same event refresh the panel.
"""

from __future__ import annotations

import json
from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic.edit import CreateView
from django.views.generic.edit import UpdateView

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import Workspace

#: The map shell fires this on every library mutation; the Built Forms panel
#: (and the paint toolbar's built-form picker) listen for it and re-fetch.
BUILT_FORMS_CHANGED_EVENT = "built-forms-changed"


def built_forms_panel_context(workspace: Workspace) -> dict[str, object]:
    """Context for the map shell's Built Forms panel and its re-renders."""
    return {
        "workspace": workspace,
        "building_types": BuildingType.objects.filter(workspace=workspace),
        "place_types": PlaceType.objects.filter(workspace=workspace),
    }


def _changed(*, toast: str | None = None) -> dict[str, object]:
    """``HX-Trigger`` payload announcing a library mutation.

    The event is what keeps every other view of the library current — the
    panel's own lists and the paint toolbar's picker — so a caller that only
    needs those refreshed can answer with an empty body (see the delete
    views), while the create/edit forms additionally re-render themselves.
    """
    payload: dict[str, object] = {BUILT_FORMS_CHANGED_EVENT: True}
    if toast:
        payload["show-toast"] = toast
    return payload


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
            context = self.get_context_data(form=form)  # type: ignore[attr-defined]
            return render(
                self.request,
                self.get_template_names()[0],
                context,
            )
        return super().form_invalid(form)  # type: ignore[misc, no-any-return]


# ── WorkspaceScopedMixin ──────────────────────────────────────────────


class WorkspaceScopedMixin:
    """Resolves ``self.workspace`` from the ``workspace_pk`` URL kwarg.

    BuildingTypes and PlaceTypes belong to exactly one workspace, so every
    CRUD view for them needs the workspace up front: to scope the queryset
    (an edit can't reach another workspace's row), to stamp new rows on
    create, and to build the redirect back to that workspace's map.
    """

    kwargs: dict[str, Any]
    workspace: Workspace

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.workspace = get_object_or_404(Workspace, pk=kwargs["workspace_pk"])
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_queryset(self) -> Any:
        return super().get_queryset().filter(workspace=self.workspace)  # type: ignore[misc]

    def form_valid(self, form: Any) -> HttpResponse:
        # Create/UpdateView's ModelForm needs the workspace stamped; the
        # delete views are plain functions and never reach this.
        if hasattr(form, "instance"):
            form.instance.workspace = self.workspace
        return super().form_valid(form)  # type: ignore[misc, no-any-return]

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=[self.workspace.pk])  # type: ignore[attr-defined]


# ── BuiltFormPanelMixin ───────────────────────────────────────────────


class BuiltFormPanelMixin(HtmxResponseMixin):
    """Saves a built form and keeps the map's drawer showing it.

    The library is a map panel, so there is no list page left to redirect to:
    a save re-renders the saved form (the map's right-hand drawer holds it)
    and fires ``built-forms-changed`` so the panel's own lists — and the paint
    toolbar's picker — pick the change up. A non-htmx visit (the create/edit
    URL opened directly) still redirects to the workspace map, which is where
    the library now lives.

    Subclasses MUST define ``edit_url_name``: a create re-renders the form of
    the row it just made, so it has to post to that row's edit URL next rather
    than to the create URL a second time.
    """

    edit_url_name: str
    workspace: Workspace

    def get_success_url(self) -> str:
        return reverse("workspace:workspace_map", args=[self.workspace.pk])

    def panel_form_action(self) -> str:
        """URL the re-rendered form must POST to."""
        obj = getattr(self, "object", None)
        if obj is None:
            return self.request.path
        return reverse(self.edit_url_name, args=[self.workspace.pk, obj.pk])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["form_action"] = self.panel_form_action()
        context["panel_form"] = bool(getattr(self.request, "htmx", False))
        context["cancel_url"] = reverse(
            "workspace:workspace_map", args=[self.workspace.pk]
        )
        # BuildingType carries 25 fields; the default 400px drawer would show
        # them one screenful at a time (see .map-shell__right-panel.wide).
        context["wide_panel"] = True
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        self.object = form.save()
        if not getattr(self.request, "htmx", False):
            return HttpResponseRedirect(self.get_success_url())
        response = render(
            self.request,
            self.get_template_names()[0],
            self.get_context_data(form=form),
        )
        response["HX-Trigger"] = json.dumps(_changed(toast=f"Saved {self.object}"))
        return response


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
            "du_type",
            "parking_spaces_per_unit",
            "parking_spaces_per_1000sqft",
            "parking_sqft_per_space",
            "ite_land_use_code",
            "land_development_category",
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
class BuildingTypeCreateView(WorkspaceScopedMixin, BuiltFormPanelMixin, CreateView):
    """Create a new BuildingType in a workspace."""

    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    edit_url_name = "workspace:building_type_edit"


@method_decorator(auth_method, name="dispatch")
class BuildingTypeUpdateView(WorkspaceScopedMixin, BuiltFormPanelMixin, UpdateView):
    """Edit an existing BuildingType."""

    model = BuildingType
    form_class = BuildingTypeForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    edit_url_name = "workspace:building_type_edit"


# ── Place Type CRUD ─────────────────────────────────────────────────────


@method_decorator(auth_method, name="dispatch")
class PlaceTypeCreateView(WorkspaceScopedMixin, BuiltFormPanelMixin, CreateView):
    """Create a new PlaceType in a workspace."""

    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    edit_url_name = "workspace:place_type_edit"


@method_decorator(auth_method, name="dispatch")
class PlaceTypeUpdateView(WorkspaceScopedMixin, BuiltFormPanelMixin, UpdateView):
    """Edit an existing PlaceType."""

    model = PlaceType
    form_class = PlaceTypeForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    edit_url_name = "workspace:place_type_edit"


# ── Delete Views ────────────────────────────────────────────────────────


@require_POST
@login_required
def building_type_delete(
    request: HttpRequest, workspace_pk: int, pk: int
) -> HttpResponse:
    """Delete a BuildingType; the panel refreshes off the event.

    The type's ``PlaceTypeBuildingTypeMix`` rows cascade with it, so the
    whole panel re-renders from the ``built-forms-changed`` event rather than
    this response carrying a body — both lists can change. A plain POST
    (no htmx, so nothing can consume the event) lands back on the map.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    building_type = get_object_or_404(BuildingType, pk=pk, workspace=workspace)
    name = str(building_type)
    building_type.delete()

    if not getattr(request, "htmx", False):
        return HttpResponseRedirect(
            reverse("workspace:workspace_map", args=[workspace.pk])
        )

    response = HttpResponse()
    response["HX-Trigger"] = json.dumps(_changed(toast=f"Deleted {name}"))
    return response


@require_POST
@login_required
def place_type_delete(request: HttpRequest, workspace_pk: int, pk: int) -> HttpResponse:
    """Delete a PlaceType; the panel refreshes off the event."""
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    place_type = get_object_or_404(PlaceType, pk=pk, workspace=workspace)
    name = str(place_type)
    place_type.delete()

    if not getattr(request, "htmx", False):
        return HttpResponseRedirect(
            reverse("workspace:workspace_map", args=[workspace.pk])
        )

    response = HttpResponse()
    response["HX-Trigger"] = json.dumps(_changed(toast=f"Deleted {name}"))
    return response
