"""View for column stitching / imputation."""

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
from brewgis.workspace.tasks import run_column_stitching


class StitchForm(forms.Form):
    """Form to configure column stitching / imputation."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.label_class = "form-label"
        self.helper.field_class = "mb-3"

    STRATEGY_CHOICES = [
        ("constant", "Constant Default Value"),
        ("built_form_default", "Built Form Default"),
    ]

    workspace = forms.ModelChoiceField(
        queryset=Workspace.objects.all(),
        label="Workspace",
    )
    table = forms.CharField(
        max_length=128,
        label="Target Table",
        help_text="Table with missing values to fill.",
    )
    target_column = forms.CharField(
        max_length=64,
        label="Column to Fill",
        help_text="Name of the column with NULL values.",
    )
    strategy = forms.ChoiceField(
        choices=STRATEGY_CHOICES,
        label="Imputation Strategy",
    )
    default_value = forms.FloatField(
        required=False,
        label="Default Value",
        help_text="Constant value to use (required for 'constant' strategy).",
    )
    source_table = forms.CharField(
        max_length=128,
        required=False,
        label="Source Table",
        help_text="Source table (required for 'area_proportional').",
    )
    source_column = forms.CharField(
        max_length=64,
        required=False,
        label="Source Column",
        help_text="Column on source table (required for 'area_proportional').",
    )


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class StitchView(FormView):
    """View to run column stitching / imputation."""

    form_class = StitchForm
    template_name = "form.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["title"] = "Stitch & Fill"
        return context

    def form_valid(self, form: StitchForm) -> HttpResponse:
        data = form.cleaned_data
        workspace: Workspace = data["workspace"]

        run = DataImportRun.objects.create(
            workspace=workspace,
            import_type="stitch",
            params={
                "table": data["table"],
                "target_column": data["target_column"],
                "strategy": data["strategy"],
                "default_value": data.get("default_value"),
                "source_table": data.get("source_table"),
                "source_column": data.get("source_column"),
            },
            status="pending",
        )

        run_column_stitching.delay(
            run_pk=run.pk,
            schema=workspace.db_schema,
            table=data["table"],
            target_column=data["target_column"],
            strategy=data["strategy"],
            default_value=data.get("default_value"),
            source_table=data.get("source_table"),
            source_column=data.get("source_column"),
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
