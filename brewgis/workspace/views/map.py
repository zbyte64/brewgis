from django.shortcuts import get_object_or_404, render
from ninja import ModelSchema
from pydantic import BaseModel, ConfigDict, Field

from ..models import Scenario, Layer, ScenarioLayer


class ScenarioLayerSchema(ModelSchema):
    tiles_url: str = Field(alias='resolve_tiles_url')
    
    class Meta: 
        model = ScenarioLayer
        exclude = ['id', 'layer']


class LayerSchema(ModelSchema):
    class Meta:
        model = Layer
        exclude = ['id']


class BoundLayerSchema(LayerSchema, ScenarioLayerSchema):
    pass


def view_scenario_map(request, pk):
    scenario = get_object_or_404(Scenario, pk=pk)
    scenario_layers = scenario.scenario_layers.all()
    merged_layers = [ 
        {
            **LayerSchema.model_validate(sl.layer).model_dump(), 
            **ScenarioLayerSchema.model_validate(sl).model_dump()
        } 
        for sl in scenario_layers
    ]
    context = {
        'layers': merged_layers,
        'workspace': scenario.workspace,
    }
    return render(request, 'workspace_map.html', context)