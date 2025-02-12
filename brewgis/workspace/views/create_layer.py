from ..models import Layer, Scenario, ScenarioLayer, Workspace
from django.contrib.auth.decorators import user_passes_test
from django import forms
from django.utils.decorators import method_decorator
from django.views.generic.edit import CreateView


class CreateLayerForm(forms.ModelForm):
    # name?
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all())
    # TODO scenario

    class Meta:
        model = ScenarioLayer
        fields = ['db_table']


def get_default_scenario(workspace: Workspace):
    return Scenario.objects.get_or_create(workspace=workspace, name='default')[0]


def create_layer(workspace: Workspace, db_table: str, name: str | None=None):
    if name is None:
        scenario = get_default_scenario(workspace)
    else:
        scenario = workspace.scenarios.get(name=name)
    layer = Layer.objects.create(workspace=workspace)
    return ScenarioLayer.objects.create(scenario=scenario, db_table=db_table, layer=layer)
    

@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class CreateLayerView(CreateView):
    form_class = CreateLayerForm
    template_name = "form.html"

    def form_valid(self, form: CreateLayerForm):
        data = form.cleaned_data
        workspace: Workspace = data['workspace']
        return create_layer(workspace, data['db_table'])
        # TODO return a response

