import json

from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from ninja import ModelSchema

from brewgis.workspace.models import Layer
from brewgis.workspace.models import Workspace
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.symbology.generator import generate_maplibre_style
from django.conf import settings


class LayerSchema(ModelSchema):
    class Meta:
        model = Layer
        exclude = ["id"]


def view_workspace_map(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    workspace = get_object_or_404(Workspace, pk=workspace_pk)
    layers = workspace.layers.all()
    layer_data = []
    for layer in layers:
        data = LayerSchema.model_validate(layer).model_dump()
        data["source"] = layer.to_maplibre_source()

        if settings.TILE_SERVER_BACKEND == "tipg":
            data["source-layer"] = layer.db_table

        # Merge symbology-generated paint/layout if available
        try:
            config = layer.symbology
            style = generate_maplibre_style(config)
            data["paint"] = style["paint"]
            data["layout"] = style["layout"]
        except SymbologyConfig.DoesNotExist:
            pass
        layer_data.append(data)

    context = {
        "layers_json": json.dumps(layer_data),
        "viewport_json": json.dumps(
            {
                "center": [0, 0],
                "zoom": 1,
            },
        ),
        "workspace": workspace,
    }
    return render(request, "workspace_map.html", context)
