"""Select a workspace's base canvas source table.

A workspace's base canvas is the parcel/feature table that scenarios paint
over (``Workspace.base_table``, defaulting to the shared ``public.base_canvas``
table). This lets a workspace instead point at a SQLMesh-generated table that
already has every required base-canvas column (see
``services.sqlmesh_tables.list_base_canvas_candidates``), skipping the manual
ETL pipeline entirely.

The form also carries the workspace's built-form fill toggle
(``Workspace.fill_built_form``). With it on, the selected source is left exactly
as it is and a *new* table is materialized for the workspace to read instead
(``models/base_canvas/built_form_fill.py``): the closest-matching Building Type
fills the NULL built-form columns. The workspace's effective base layer — what
the map, the canvas views and the analysis models read — is resolved in one
place, ``Workspace.effective_base_table``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any

from crispy_forms.helper import FormHelper
from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import FormView

from brewgis.sqlmesh.macros.built_form_fill_blueprints import MODEL_SCHEMA
from brewgis.workspace.analysis.data_export import ensure_export_exists_isolated
from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import register_result_layer
from brewgis.workspace.analysis.sqlmesh_runner import purge_models_from_environments
from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.scenario_canvas import canvas_model_selector
from brewgis.workspace.services.scenario_canvas import modeled_scenarios
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates
from brewgis.workspace.views.built_forms import HtmxResponseMixin

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


def _base_canvas_choices() -> list[tuple[str, str]]:
    return [(info.qualified, info.qualified) for info in list_base_canvas_candidates()]


def _fill_model_fqn(workspace_pk: int) -> str:
    """SQLMesh's name for *workspace_pk*'s built-form fill model.

    Mirrors ``services.scenario_canvas.canvas_model_fqn``: the identifier parts
    are double-quoted so the FQN survives selector parsing.
    """
    return f'brewgis."{MODEL_SCHEMA}"."fill_{workspace_pk}"'


class SelectBaseCanvasForm(forms.Form):
    base_table = forms.ChoiceField(
        label="Base canvas table",
        choices=_base_canvas_choices,
        help_text="Only SQLMesh tables with every required base canvas column are listed.",
    )
    fill_built_form = forms.BooleanField(
        required=False,
        label="Fill built form by closest matching",
        help_text=(
            "Assign each parcel the closest-matching Building Type. The match "
            "replaces the parcel's built_form_key; du, pop, hh and emp are filled "
            "where they are NULL. Materializes a new table; the selected source is "
            "not modified."
        ),
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class SelectBaseCanvasView(HtmxResponseMixin, FormView):
    form_class = SelectBaseCanvasForm
    template_name = "form.html"
    success_url_name = "workspace:workspace_map"
    extra_context = {"title": "Select Base Canvas"}

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.workspace = get_object_or_404(Workspace, pk=kwargs["workspace_pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial["base_table"] = self.workspace.base_table
        initial["fill_built_form"] = self.workspace.fill_built_form
        return initial

    def get_redirect_url(self) -> str:
        return reverse(self.success_url_name, args=[self.workspace.pk])

    def form_valid(self, form: Any) -> HttpResponse:
        source = form.cleaned_data["base_table"]
        fill = form.cleaned_data["fill_built_form"]
        # Persisted *before* the plan: ``built_form_fill_profiles()`` reads
        # these columns while loading the project, so the fill model only
        # exists in the plan that is about to run once the flag is on disk.
        self.workspace.fill_built_form = fill
        self.workspace.base_table = source
        self.workspace.save(update_fields=["base_table", "fill_built_form"])

        # The fill and the canvas models over it go into a *single* plan. Any
        # plan promotes the whole environment's virtual layer, which recreates
        # every snapshot's view — including the canvases whose base this form
        # just changed. A canvas that a plan selects but does not *build* is
        # promoted anyway, with its view pointed at a physical object the plan
        # never created; that fails the promotion, which fails this request
        # before the canvases are ever rebuilt, and leaves the state broken for
        # the next plan too. Building both in one plan leaves no such window.
        selectors = [
            canvas_model_selector(scenario)
            for scenario in modeled_scenarios(
                self.workspace.scenarios.filter(scenario_type=ScenarioType.ALTERNATIVE)
            )
        ]
        if fill:
            # The model's JOIN source. Exported on its own connection so it is
            # committed before the plan's engine adapter reads it.
            ensure_export_exists_isolated(
                self.workspace, schema=self.workspace.db_schema, table="built_forms"
            )
            # The selected source model is already materialized (the picker only
            # offers existing tables), so the fill plus the canvases over it are
            # the whole selection.
            selectors.insert(0, _fill_model_fqn(self.workspace.pk))
        else:
            # Flipping the flag off de-lists this workspace's fill model from
            # the blueprint; drop the now-orphaned snapshot so a later plan
            # never promotes a model the project no longer defines.
            purge_models_from_environments([_fill_model_fqn(self.workspace.pk)])
        if selectors:
            run_sqlmesh_plan(
                environment="prod",
                select=selectors,
                # A Python model's SQLMesh fingerprint covers its *definition*,
                # not the SQL its ``execute`` returns — so a change to the fill
                # rule (or to the library it matches against) leaves the
                # snapshot looking unchanged, and the workspace would keep
                # reading a table built by the previous rule. Flipping the
                # switch is a request to rebuild, so the fill model is always
                # recomputed; the canvases over it follow their parent's data
                # change into the same plan.
                restate_models=[_fill_model_fqn(self.workspace.pk)] if fill else False,
                auto_apply=True,
                no_prompts=True,
            )
        schema, table = self.workspace.effective_base_table().split(".", 1)
        register_result_layer(
            self.workspace.pk,
            schema,
            table,
            key=BASE_CANVAS_LAYER_KEY,
            name="Base Canvas",
            description=f"Workspace base canvas ({self.workspace.effective_base_table()})",
        )
        logger.info(
            "Workspace %s base_table=%s fill_built_form=%s (planned %s)",
            self.workspace.pk,
            self.workspace.base_table,
            self.workspace.fill_built_form,
            selectors,
        )
        return super().form_valid(form)
