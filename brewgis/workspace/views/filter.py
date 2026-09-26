"""Filter views for BrewGIS — expression-tree filter CRUD via htmx."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.decorators import user_passes_test
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
from brewgis.workspace.services.spatial_filter import has_spatial_node
from brewgis.workspace.services.spatial_filter import refresh_spatial_filter_layer

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


def _filter_list_context(layer: Layer) -> dict[str, Any]:
    """Build shared context for filter list partial."""
    return {
        "layer": layer,
        "filters": layer.filters.all(),
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


def _active_filters_for_layer(layer: Layer) -> list[LayerFilter]:
    """Return active filters for a layer."""
    return list(layer.filters.filter(is_active=True))


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
        was_spatial = flt.is_active and has_spatial_node(flt.filter_json)
        flt.filter_json = parsed
        flt.save()
        # A spatial condition lives in a materialized table, so editing one into
        # or out of the filter changes which table the layer draws from. The
        # plan is synchronous, like the base-canvas fill toggle.
        source_changed = was_spatial or (flt.is_active and has_spatial_node(parsed))
        if source_changed:
            refresh_spatial_filter_layer(flt.layer)
        context = _filter_list_context(flt.layer)
        response = render(request, "workspace/filter/list.html", context)
        if source_changed:
            # The map resolves the tile source from the database on render — see
            # ``layer_filter_toggle`` for why this cannot be a MapLibre filter.
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
    """Delete a filter and return the list partial."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    layer = flt.layer
    # Deleting the last active spatial filter must drop the layer's materialized
    # filter table, so the layer goes back to reading its declared source (and
    # the page must reload to pick that source up — see ``layer_filter_toggle``).
    was_active_spatial = flt.is_active and has_spatial_node(flt.filter_json)
    flt.delete()
    if was_active_spatial:
        refresh_spatial_filter_layer(layer)
    context = _filter_list_context(layer)
    response = render(request, "workspace/filter/list.html", context)
    if was_active_spatial:
        response["HX-Refresh"] = "true"
    return response


@require_POST
@user_passes_test(lambda u: u.is_authenticated)
def layer_filter_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Toggle the active state of a filter."""
    flt = get_object_or_404(LayerFilter, pk=pk)
    flt.is_active = not flt.is_active
    flt.save()

    layer = flt.layer
    if has_spatial_node(flt.filter_json):
        # Toggling a spatial filter on materializes the layer's filtered table
        # and toggling it off drops it — either way the layer's tile source
        # changes, so the plan/purge runs and the page reloads. The map resolves
        # a layer's tile source from the database when it renders, so setting a
        # MapLibre filter cannot show the change: the browser keeps requesting
        # the table the page was loaded with. The base-canvas fill toggle answers
        # the same problem with a page load.
        refresh_spatial_filter_layer(layer)
        response = render(
            request, "workspace/filter/list.html", _filter_list_context(layer)
        )
        response["HX-Refresh"] = "true"
        return response

    # Build combined filter expression for all active filters on this layer
    compiler = FilterCompiler()
    active = layer.filters.filter(is_active=True)
    if active:
        combined = {
            "type": "group",
            "operator": "AND",
            "children": [f.filter_json for f in active],
        }
        maplibre_filter = compiler.compile_to_maplibre(combined)
    else:
        maplibre_filter = None

    context = _filter_list_context(layer)
    response = render(request, "workspace/filter/list.html", context)
    response["HX-Trigger"] = json.dumps(
        {
            "filter-preview": {
                "layerKey": layer.db_table,
                "filterExpression": maplibre_filter,
            },
        }
    )
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
            "is_active": flt.is_active,
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
