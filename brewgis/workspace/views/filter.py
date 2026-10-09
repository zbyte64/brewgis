"""Filter views for BrewGIS — expression-tree filter CRUD via htmx."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods
from django.views.decorators.http import require_POST

from brewgis.workspace.analysis.layer_registry import _get_table_columns
from brewgis.workspace.models import Layer
from brewgis.workspace.models import LayerFilter
from brewgis.workspace.services.filter_compiler import FilterCompiler
from brewgis.workspace.services.spatial_filter import FilterNotMaterializableError
from brewgis.workspace.services.spatial_filter import apply_filter
from brewgis.workspace.services.spatial_filter import refresh_filter_models
from brewgis.workspace.services.spatial_filter import unapply_filter

_GEOMETRY_DATA_TYPES = {"geometry", "geography", "USER-DEFINED"}


def _column_metadata(layer: Layer) -> list[dict[str, Any]]:
    """Field choices for the filter-builder component: name + numeric flag."""
    schema = layer.db_schema or layer.workspace.db_schema
    columns = _get_table_columns(schema, layer.db_table)
    return [
        {"name": c["column_name"], "numeric": c["numeric"]}
        for c in columns
        if c["data_type"] not in _GEOMETRY_DATA_TYPES
    ]


def _filter_list_context(
    layer: Layer, apply_error: str | None = None
) -> dict[str, Any]:
    """Build shared context for filter list partial."""
    return {
        "layer": layer,
        "filters": layer.filters.select_related("output_layer"),
        "apply_error": apply_error,
    }


def _spatial_layer_options(layer: Layer) -> list[dict[str, Any]]:
    """Other-layer choices for a spatial condition in the filter builder.

    ``value`` is the ``schema.table`` the compiled predicate reads (the condition
    stores it verbatim), ``geometry`` the other table's geometry column, so
    picking a layer in the builder fixes both. Only layers whose geometry
    ``geometry_columns`` actually registers are offered — a layer with nothing
    to intersect against would produce a condition that materializes to a parse
    error. Point layers are ordinary layers with a point geometry: a POI layer
    is a distance buffer around its points, and needs no special case.
    """
    from brewgis.workspace.services.spatial_filter import registered_geometry_column

    options: list[dict[str, Any]] = []
    others = layer.workspace.layers.exclude(pk=layer.pk).order_by("key")
    for other in others:
        schema = other.db_schema or other.workspace.db_schema
        geometry = registered_geometry_column(schema, other.db_table)
        if geometry is None:
            continue
        options.append(
            {
                "value": f"{schema}.{other.db_table}",
                "label": other.name or other.key,
                "geometry": geometry,
            }
        )
    return options


def _editor_context(
    layer: Layer,
    flt: LayerFilter | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build shared context for the filter editor partial."""
    return {
        "layer": layer,
        "filter": flt,
        "filter_value": flt.filter_json if flt else {},
        "error": error,
        "columns": _column_metadata(layer),
        "layers": _spatial_layer_options(layer),
    }


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_filter_list(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Return filter list partial for a layer."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    context = _filter_list_context(layer)
    return render(request, "workspace/filter/list.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_filter_create(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Create a new filter for a layer (GET=form, POST=create)."""
    layer = get_object_or_404(Layer, pk=layer_pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/filter/editor.html",
                _editor_context(layer, error="Filter name is required."),
            )
        raw_json = request.POST.get("filter_json", "{}")
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return render(
                request,
                "workspace/filter/editor.html",
                _editor_context(layer, error=f"Invalid filter JSON: {e}"),
            )
        flt = LayerFilter.objects.create(
            layer=layer,
            name=name,
            filter_json=parsed,
        )
        # Render the list partial with the new filter included
        context = _filter_list_context(layer)
        return render(request, "workspace/filter/list.html", context)
    # GET — return empty editor
    return render(
        request,
        "workspace/filter/editor.html",
        _editor_context(layer),
    )


@user_passes_test(lambda u: u.is_authenticated)
@require_http_methods(["GET", "POST"])
def layer_filter_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing filter (GET=form, POST=update)."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workspace/filter/editor.html",
                _editor_context(flt.layer, flt, error="Filter name is required."),
            )
        raw_json = request.POST.get("filter_json", "{}")
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return render(
                request,
                "workspace/filter/editor.html",
                _editor_context(flt.layer, flt, error=f"Invalid filter JSON: {e}"),
            )
        flt.name = name
        flt.filter_json = parsed
        applied = flt.filtered_layer is not None
        try:
            with transaction.atomic():
                flt.save()
                if applied:
                    # The filtered layer is a materialized table, so an edited
                    # tree has to be rebuilt before the map reads it again.
                    refresh_filter_models(flt)
        except FilterNotMaterializableError as e:
            return render(
                request,
                "workspace/filter/editor.html",
                _editor_context(flt.layer, flt, error=str(e)),
            )
        response = render(
            request, "workspace/filter/list.html", _filter_list_context(flt.layer)
        )
        if applied:
            # The map resolves layers and their tiles when the page renders.
            response["HX-Refresh"] = "true"
        return response
    # GET — return editor with existing data
    return render(
        request,
        "workspace/filter/editor.html",
        _editor_context(flt.layer, flt),
    )


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a filter (and its filtered layer, by cascade); return the list partial."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    layer = flt.layer
    applied = flt.filtered_layer is not None
    flt.delete()
    response = render(
        request, "workspace/filter/list.html", _filter_list_context(layer)
    )
    if applied:
        # The cascade removed the filtered layer: drop its model, and reload so
        # the map and the layer list lose it too.
        refresh_filter_models()
        response["HX-Refresh"] = "true"
    return response


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Apply a filter as a new layer, or remove the layer it was applied as.

    Applying never touches the filtered layer: the filter's rows are
    materialized as a new table and registered as a new Layer beside it
    (``services.spatial_filter.apply_filter``). The plan is synchronous, like
    the base-canvas fill toggle, and the page reloads because the map resolves
    its layers and their tile sources when it renders.
    """
    flt = get_object_or_404(LayerFilter, pk=pk)
    layer = flt.layer
    if flt.filtered_layer is not None:
        unapply_filter(flt)
    else:
        try:
            with transaction.atomic():
                apply_filter(flt)
        except FilterNotMaterializableError as e:
            return render(
                request,
                "workspace/filter/list.html",
                _filter_list_context(layer, apply_error=str(e)),
            )
    response = render(
        request, "workspace/filter/list.html", _filter_list_context(layer)
    )
    response["HX-Refresh"] = "true"
    return response


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_preview_map(request: HttpRequest, pk: int) -> HttpResponse:
    """Apply (or remove) a filter on the map without saving state."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    layer = flt.layer

    compiler = FilterCompiler()
    maplibre_filter = compiler.compile_to_maplibre(flt.filter_json)

    response = HttpResponse()
    response["HX-Trigger"] = json.dumps(
        {
            "filter-preview": {
                "layerKey": layer.db_table,
                "filterExpression": maplibre_filter,
            },
        }
    )
    return response


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_filter_preview(request: HttpRequest, pk: int) -> JsonResponse:
    """Return a JSON preview of how many features this filter matches.

    For now, returns the filter expression for client-side evaluation.
    Server-side count queries can be added when a specific source table
    is linked to the layer.
    """
    flt = get_object_or_404(LayerFilter, pk=pk)
    return JsonResponse(
        {
            "id": flt.pk,
            "name": flt.name,
            "filtered_layer": filtered.key
            if (filtered := flt.filtered_layer)
            else None,
            "filter_json": flt.filter_json,
            "expression": _human_readable_expression(flt.filter_json),
        }
    )


def _human_readable_expression(filter_json: dict) -> str:
    """Convert a filter expression tree to a human-readable string."""
    if not filter_json or not isinstance(filter_json, dict):
        return "(empty filter)"
    filter_type = filter_json.get("type", "")
    if filter_type == "group":
        operator = filter_json.get("operator", "AND")
        children = filter_json.get("children", [])
        parts = [_human_readable_expression(c) for c in children if c]
        if not parts:
            return "(empty group)"
        return f"({f' {operator} '.join(parts)})"
    if filter_type == "column":
        field = filter_json.get("field", "?")
        op = filter_json.get("operator", "?")
        value = filter_json.get("value", "")
        op_display = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
            "contains": "contains",
            "is_null": "is null",
            "is_not_null": "is not null",
        }
        display_op = op_display.get(op, op)
        if op in ("is_null", "is_not_null"):
            return f"{field} {display_op}"
        return f"{field} {display_op} {value}"
    if filter_type == "spatial":
        mode = filter_json.get("mode", "intersects")
        source = filter_json.get("source", "?")
        buffer_m = filter_json.get("buffer_meters")
        buffer = f" +{buffer_m}m" if buffer_m else ""
        return f"[{mode}: {source}{buffer}]"
    if filter_type == "geometry":
        geo_type = filter_json.get("geometry_type", "?")
        return f"[geometry: {geo_type}]"
    if filter_type == "join":
        join_layer = filter_json.get("join_layer", "?")
        return f"[join: {join_layer}]"
    return f"[{filter_type}]"
