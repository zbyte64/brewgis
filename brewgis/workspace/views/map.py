"""Map view — renders workspace map with optional scenario paint mode."""

from __future__ import annotations

import json
import math
import uuid
from typing import TYPE_CHECKING

from django.db import connection
from django.db.models import Max
from django.http import Http404
from django.views.decorators.http import require_safe

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.urls import reverse
from ninja import ModelSchema

from brewgis.workspace.analysis.layer_registry import PAINTED_FEATURES_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import ensure_painted_features_layer
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import Basemap
from brewgis.workspace.models import Layer
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.canvas_view_manager import build_paintable_column_meta
from brewgis.workspace.symbology.generator import generate_maplibre_style


class LayerSchema(ModelSchema):
    class Meta:
        model = Layer
        exclude = ["id"]


_MIN_AUTO_ZOOM = 2.0
_MAX_AUTO_ZOOM = 16.0
_AUTO_ZOOM_PADDING = 1.0


def _table_extent(schema: str, table: str) -> tuple[float, float, float, float] | None:
    """Return (min_lng, min_lat, max_lng, max_lat) for a table's geometry, or None."""
    try:
        with connection.cursor() as cursor:
            # schema/table are quoted identifiers from Workspace/Layer
            # records, not raw user input.
            cursor.execute(
                f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) "  # noqa: S608
                f"FROM (SELECT ST_Extent(geometry) AS e "
                f"FROM {connection.ops.quote_name(schema)}"
                f".{connection.ops.quote_name(table)}) t"
            )
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not row or row[0] is None:
        return None
    return row


def _zoom_for_extent(
    min_lng: float, min_lat: float, max_lng: float, max_lat: float
) -> float:
    """Rough zoom level that fits a lng/lat bounding box, clamped to a sane range."""
    lng_span = max(max_lng - min_lng, 1e-6)
    lat_span = max(max_lat - min_lat, 1e-6)
    zoom = min(math.log2(360.0 / lng_span), math.log2(180.0 / lat_span))
    return max(_MIN_AUTO_ZOOM, min(zoom - _AUTO_ZOOM_PADDING, _MAX_AUTO_ZOOM))


def _resolve_viewport(workspace: Workspace) -> dict[str, object]:
    """Return ``{"center": [lng, lat], "zoom": z}`` for the initial map view.

    ``Workspace.center_lng``/``center_lat`` default to ``0.0`` (Null Island),
    so a freshly-created workspace that never had these set explicitly would
    otherwise open off the coast of Africa. When both are still at that
    default, this instead fits to the extent of the workspace's base table
    (or, failing that, one of its layers) and persists the result so future
    loads skip the recomputation.
    """
    if workspace.center_lng or workspace.center_lat:
        return {
            "center": [workspace.center_lng, workspace.center_lat],
            "zoom": workspace.zoom,
        }

    candidates: list[tuple[str, str]] = []
    if workspace.base_table and "." in workspace.base_table:
        schema, table = workspace.base_table.split(".", 1)
        candidates.append((schema, table))
    for layer in workspace.layers.all():
        schema = layer.db_schema or workspace.db_schema
        candidates.append((schema, layer.db_table))

    for schema, table in candidates:
        extent = _table_extent(schema, table)
        if extent is None:
            continue
        min_lng, min_lat, max_lng, max_lat = extent
        center = [(min_lng + max_lng) / 2.0, (min_lat + max_lat) / 2.0]
        zoom = _zoom_for_extent(min_lng, min_lat, max_lng, max_lat)
        Workspace.objects.filter(pk=workspace.pk).update(
            center_lng=center[0], center_lat=center[1], zoom=zoom
        )
        return {"center": center, "zoom": zoom}

    return {
        "center": [workspace.center_lng, workspace.center_lat],
        "zoom": workspace.zoom,
    }


def view_workspace_map(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Render the workspace map, optionally with scenario paint mode.

    Supports ``?scenario=<pk>`` query parameter to enable paint mode,
    which adds a canvas view layer and paint toolbar to the template.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    # Check for scenario query parameter
    scenario_id = request.GET.get("scenario")
    scenario: Scenario | None = None
    canvas_view_name: str | None = None
    paintable_column_meta: list[dict[str, str]] = []
    built_forms_data: dict[str, list[dict[str, object]]] = {}
    paint_url: str = ""
    clear_url: str = ""
    bf_paint_url: str = ""
    bf_match_url: str = ""
    bf_fill_url: str = ""
    history_url: str = ""
    undo_url: str = ""

    if scenario_id:
        scenario = get_object_or_404(Scenario, pk=int(scenario_id), workspace=workspace)
        # Build canvas view source (the COALESCE view for this scenario)
        schema = scenario.target_schema
        view_name = f"scenario_{scenario.slug}_canvas"
        canvas_view_name = view_name
        canvas_source_id = f"{schema}.{view_name}"
        ensure_painted_features_layer(workspace, schema=schema, table=view_name)

        # Build absolute base URL manually — must NOT go through
        # build_absolute_uri()/iri_to_uri() which URL-encodes {z}/{x}/{y}
        # template placeholders.
        _request_scheme_host = f"{request.scheme}://{request.get_host()}"

        # Martin's tile responses carry no Cache-Control/Expires header, so
        # a plain page reload can have the browser reuse a previously
        # cached tile for an extent painted since — the canvas view itself
        # is always live (see canvas_view_manager.refresh_canvas_view), but
        # the *browser* doesn't know that. Stamp the tile URL with the most
        # recent paint write for this scenario so a repaint always changes
        # the URL (and therefore the browser's cache key), the same way
        # brew-gis-map.ts's refreshCanvasTiles() cache-busts mid-session.
        last_painted = PaintedCanvas.objects.filter(scenario=scenario).aggregate(
            Max("painted_at")
        )["painted_at__max"]
        _version_qs = f"?v={last_painted.timestamp():.0f}" if last_painted else ""

        if workspace.tile_server_backend == "martin":
            canvas_tiles_url = f"{_request_scheme_host}/martin/{canvas_source_id}/{{z}}/{{x}}/{{y}}{_version_qs}"
        else:
            canvas_tiles_url = (
                f"{_request_scheme_host}"
                f"/tipg/collections/{canvas_source_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}{_version_qs}"
            )

        # Build column metadata for the paint toolbar dropdown
        paintable_column_meta = build_paintable_column_meta()

        # Build built forms data for toolbar dropdowns
        bts = BuildingType.objects.filter(workspace=workspace).order_by("name")
        pts = PlaceType.objects.filter(workspace=workspace).order_by("name")
        built_forms_data = {
            "building_types": [{"id": bt.pk, "name": bt.name} for bt in bts],
            "place_types": [{"id": pt.pk, "name": pt.name} for pt in pts],
        }

        # Build paint action URLs via reverse() — these previously
        # hardcoded a "/workspace/" prefix that doesn't match the actual
        # URL patterns (which mount directly under the workspace_pk), so
        # every Apply/Clear/Undo/History request 404'd.
        paint_url = request.build_absolute_uri(
            reverse("workspace:paint_features", args=[workspace_pk, scenario.pk])
        )
        clear_url = request.build_absolute_uri(
            reverse("workspace:clear_paint", args=[workspace_pk, scenario.pk])
        )
        bf_paint_url = request.build_absolute_uri(
            reverse("workspace:paint_built_form", args=[workspace_pk, scenario.pk])
        )
        bf_match_url = request.build_absolute_uri(
            reverse("workspace:match_built_form", args=[workspace_pk, scenario.pk])
        )
        bf_fill_url = request.build_absolute_uri(
            reverse("workspace:fill_built_form", args=[workspace_pk, scenario.pk])
        )
        history_url = request.build_absolute_uri(
            reverse("workspace:paint_history", args=[workspace_pk, scenario.pk])
        )
        undo_url = request.build_absolute_uri(
            reverse("workspace:undo_paint", args=[workspace_pk, scenario.pk])
        )

    # Build regular layer data
    layers = workspace.layers.all()
    layer_data = []
    for layer in layers:
        is_painted_features_layer = layer.key == PAINTED_FEATURES_LAYER_KEY
        if is_painted_features_layer and not scenario:
            # This overlay has no source of its own — it only ever renders
            # against the active scenario's canvas view (below). Without a
            # scenario there's nothing to tile from, so skip it entirely
            # rather than fall through to to_maplibre_source() with no
            # db_table.
            continue

        data = LayerSchema.model_validate(layer).model_dump()
        data["id"] = layer.key
        data["type"] = layer.geometry_type
        is_base_layer = layer._source_id() == workspace.base_table  # noqa: SLF001

        if (is_base_layer or is_painted_features_layer) and scenario:
            # A scenario is active: tile this layer from the scenario's
            # canvas view (base canvas COALESCEd with any PaintedCanvas
            # overrides) instead of the raw, unpainted base table — so the
            # symbology below (breaks/colors/categories) actually reflects
            # painted values instead of silently showing stale data.
            data["source"] = {
                "type": "vector",
                "tiles": [canvas_tiles_url],
                "promoteId": "id",
            }
            base_source_layer = (
                "default"
                if workspace.tile_server_backend == "tipg"
                else canvas_source_id
            )
        else:
            data["source"] = layer.to_maplibre_source()
            if is_base_layer:
                # Same fix as the scenario canvas view below: non-numeric
                # parcel ids aren't valid native MVT feature ids, so without
                # this, click-to-inspect can never resolve a clicked feature.
                data["source"]["promoteId"] = "id"
            base_source_layer = None

        # Make tile URLs absolute (MapLibre v4+ requires absolute URLs
        # for tile sources in web worker contexts).
        # Build manually — build_absolute_uri() would URL-encode {z}/{x}/{y}.
        _request_scheme_host = f"{request.scheme}://{request.get_host()}"
        if "tiles" in data["source"]:
            data["source"]["tiles"] = [
                t if t.startswith("http") else f"{_request_scheme_host}{t}"
                for t in data["source"]["tiles"]
            ]

        # MapLibre always requires a source-layer for a vector source — it's
        # not tipg-specific. tipg's MVT layers are always named "default";
        # Martin's TileJSON confirms it names each MVT layer after the
        # source's own id (the same "{schema}.{table}" string used above).
        if base_source_layer is not None:
            data["source-layer"] = base_source_layer
        elif workspace.tile_server_backend == "tipg":
            data["source-layer"] = "default"
        else:
            data["source-layer"] = layer._source_id()  # noqa: SLF001

        # Merge symbology-generated paint/layout if available
        try:
            config = layer.symbology
            style = generate_maplibre_style(config)
            data["paint"] = style["paint"]
            data["layout"] = style["layout"]
        except SymbologyConfig.DoesNotExist:
            pass

        # Persisted visibility toggle
        data.setdefault("layout", {})
        data["layout"]["visibility"] = "visible" if layer.is_visible else "none"

        layer_data.append(data)

    # The map layer ID for the scenario canvas view (used by brew-gis-map for
    # feature selection). The painted-features Layer (see
    # ensure_painted_features_layer) is what actually renders this now — its
    # paint/visibility come from the loop above like any other Layer.
    canvas_view_layer_id = PAINTED_FEATURES_LAYER_KEY if scenario else ""
    selection_mode = request.GET.get("selection_mode", "click")

    # Layer id to click-inspect against when no scenario is active. Only
    # set if the workspace's base table has actually been registered as a
    # Layer — nothing does that automatically today, so inspect click is
    # effectively scenario-only otherwise.
    base_layer_id = ""
    for layer in layers:
        if layer._source_id() == workspace.base_table:  # noqa: SLF001
            base_layer_id = layer.key
            break

    # Build URL for the map page with scenario param
    scenario_url = ""
    if scenario:
        scenario_url = request.build_absolute_uri(
            f"/workspace/{workspace_pk}/map/?scenario={scenario.pk}"
        )

    # Resolve current basemap from session or default
    session_key = f"ws_{workspace_pk}_basemap_id"
    basemap_id_sel = request.session.get(session_key)
    basemap_style = None
    if basemap_id_sel:
        try:
            basemap_instance = Basemap.objects.get(pk=basemap_id_sel)
            resolved = basemap_instance.resolve_style()
            basemap_style = (
                json.dumps(resolved) if isinstance(resolved, dict) else resolved
            )
        except Basemap.DoesNotExist:
            basemap_style = None
    if not basemap_style:
        default_basemap = Basemap.objects.filter(is_default=True).first()
        if default_basemap:
            resolved = default_basemap.resolve_style()
            basemap_style = (
                json.dumps(resolved) if isinstance(resolved, dict) else resolved
            )
        else:
            basemap_style = json.dumps(
                {
                    "version": 8,
                    "sources": {
                        "basemap": {
                            "type": "raster",
                            "tiles": [
                                "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
                            ],
                            "tileSize": 256,
                            "attribution": (
                                '&copy; <a href="https://www.openstreetmap.org/copyright">'
                                "OpenStreetMap</a> contributors &copy;"
                                ' <a href="https://carto.com/">CARTO</a>'
                            ),
                        },
                    },
                    "layers": [
                        {
                            "id": "basemap-layer",
                            "type": "raster",
                            "source": "basemap",
                            "minzoom": 0,
                            "maxzoom": 22,
                        },
                    ],
                }
            )

    context: dict[str, object] = {
        "layers_json": json.dumps(layer_data).replace("'", "\\u0027"),
        "layer_data": layer_data,
        "viewport_json": json.dumps(_resolve_viewport(workspace)),
        "workspace": workspace,
        "scenario": scenario,
        "scenario_json": json.dumps(
            {"id": scenario.pk, "name": scenario.name, "slug": scenario.slug}
        )
        if scenario
        else "null",
        "scenario_url": scenario_url,
        "canvas_view_name": canvas_view_name if canvas_view_name else "",
        "paintable_columns": paintable_column_meta,
        "built_forms": built_forms_data,
        "paint_url": paint_url,
        "clear_url": clear_url,
        "bf_paint_url": bf_paint_url,
        "bf_match_url": bf_match_url,
        "bf_fill_url": bf_fill_url,
        "history_url": history_url if scenario else "",
        "undo_url": undo_url if scenario else "",
        "canvas_view_layer_id": canvas_view_layer_id,
        "base_layer_id": base_layer_id,
        "selection_mode": selection_mode,
        "basemap_style": basemap_style,
    }

    return render(request, "workspace_map.html", context)


@require_safe
def view_public_scenario_map(request: HttpRequest, token: str) -> HttpResponse:
    """Public read-only map view for a published scenario."""
    try:
        token_uuid = uuid.UUID(str(token))
    except (ValueError, AttributeError):
        raise Http404("Invalid token.")

    scenario = get_object_or_404(
        Scenario,
        public_token=token_uuid,
        published=True,
    )
    workspace = scenario.workspace

    layers = Layer.objects.filter(workspace=workspace).order_by("display_order")

    layer_data = []
    for layer in layers:
        source = layer.to_maplibre_source()
        if "tiles" in source:
            source["tiles"] = [request.build_absolute_uri(t) for t in source["tiles"]]
        layer_data.append(
            {
                "key": layer.key,
                "name": layer.name,
                "type": layer.geometry_type,
                "source": source,
                "source-layer": "default"
                if workspace.tile_server_backend == "tipg"
                else layer._source_id(),  # noqa: SLF001
                "symbology": layer.symbology if hasattr(layer, "symbology") else None,
                "layout": {"visibility": "visible" if layer.is_visible else "none"},
            }
        )

    context = {
        "workspace": workspace,
        "layers": layers,
        "layer_data": layer_data,
        "scenario": scenario,
        "is_public_view": True,
        "disable_paint": True,
        "public_token": token,
    }

    return render(request, "workspace_map.html", context)
