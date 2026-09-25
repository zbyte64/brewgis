"""Map view — renders workspace map with optional scenario paint mode."""

from __future__ import annotations

import json
import math
import uuid
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import user_passes_test
from django.db import connection
from django.db import transaction
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

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import PAINTED_FEATURES_LAYER_KEY
from brewgis.workspace.analysis.layer_registry import ensure_painted_features_layer
from brewgis.workspace.analysis.layer_registry import visible_layers_for_panel
from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.models import Basemap
from brewgis.workspace.models import Layer
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.canvas_view_manager import build_paintable_column_meta
from brewgis.workspace.symbology.generator import generate_maplibre_style
from brewgis.workspace.views.panels import resolve_scenario_param


class LayerSchema(ModelSchema):
    class Meta:
        model = Layer
        # `scenario` is a server-side scoping field — the frontend gets an
        # already-scoped layer list, and `id` is replaced by the layer key.
        exclude = ["id", "scenario"]


_MIN_AUTO_ZOOM = 2.0
_MAX_AUTO_ZOOM = 16.0
_AUTO_ZOOM_PADDING = 1.0

# Sanity bounds for a viewport handed in via query params. MapLibre's own
# limits: latitude is clamped to the Mercator square, zoom tops out at 24,
# and maxPitch defaults to 60 but never exceeds 85.
_MIN_LAT = -90.0
_MAX_LAT = 90.0
_MIN_ZOOM = 0.0
_MAX_ZOOM = 24.0
_MIN_PITCH = 0.0
_MAX_PITCH = 85.0


def _table_extent(schema: str, table: str) -> tuple[float, float, float, float] | None:
    """Return (min_lng, min_lat, max_lng, max_lat) for a table's geometry, or None.

    Runs in its own savepoint: a missing/renamed table (e.g. a SQLMesh output
    that hasn't materialized yet) must not poison the outer request
    transaction and take down every other query on the page with it.
    """
    try:
        with transaction.atomic(), connection.cursor() as cursor:
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


def _resolve_attribute_label(column: str) -> str:
    """Human-readable label for a symbology attribute column.

    Used by hover tooltips to show e.g. "Built Form" instead of the raw
    ``built_form_key`` column name. Falls back to a title-cased version of
    the column name for columns outside the base canvas schema (e.g.
    analysis-result tables like ``vmt_total``).
    """
    col_def = BaseCanvasSchema.get(column)
    if col_def:
        return col_def.label
    return column.replace("_", " ").title()


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


def _finite_float_param(request: HttpRequest, name: str) -> float | None:
    """Return ``?<name>`` as a finite float, or None when absent/garbage."""
    raw = request.GET.get(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _wrap_lng(value: float) -> float:
    """Wrap a longitude/bearing into [-180, 180) — the same wrap MapLibre applies."""
    return ((value + 180.0) % 360.0) - 180.0


def _query_viewport(request: HttpRequest) -> dict[str, object] | None:
    """Viewport carried over from a previous render of this page, or None.

    Switching scenarios is a plain GET reload of this same URL, so the
    template attaches the live map's center/zoom (and pitch/bearing, when
    tilted or rotated) to that request — otherwise every switch snaps the
    map back to the workspace's stored default and loses the user's place.
    Values are validated here rather than persisted: a hand-edited or stale
    query string must degrade to the workspace default (skip this) instead
    of rendering a broken map, and the workspace's own saved viewport must
    not be overwritten by someone else's pan.
    """
    lng = _finite_float_param(request, "lng")
    lat = _finite_float_param(request, "lat")
    zoom = _finite_float_param(request, "zoom")
    if lng is None or lat is None or zoom is None:
        return None
    if not (_MIN_LAT <= lat <= _MAX_LAT) or not (_MIN_ZOOM <= zoom <= _MAX_ZOOM):
        return None

    viewport: dict[str, object] = {"center": [_wrap_lng(lng), lat], "zoom": zoom}
    pitch = _finite_float_param(request, "pitch")
    if pitch is not None and _MIN_PITCH <= pitch <= _MAX_PITCH:
        viewport["pitch"] = pitch
    bearing = _finite_float_param(request, "bearing")
    if bearing is not None:
        viewport["bearing"] = _wrap_lng(bearing)
    return viewport


@user_passes_test(lambda u: u.is_authenticated)
def view_workspace_map(request: HttpRequest, workspace_pk: int) -> HttpResponse:
    """Render the workspace map, optionally with scenario paint mode.

    Supports ``?scenario=<pk>`` query parameter to enable paint mode,
    which adds a canvas view layer and paint toolbar to the template.
    """
    workspace = get_object_or_404(Workspace, pk=workspace_pk)

    # Resolve the active scenario, defaulting to the workspace's BASE
    # scenario when no ?scenario= param is given — scenario is never None
    # from here on. Paint-specific UI (toolbar, paint URLs, the
    # painted-features overlay, the canvas tile source) only applies when
    # an ALTERNATIVE scenario is active; a BASE scenario's tile source is
    # just its already-registered base canvas Layer, unchanged from
    # today's non-scenario code path.
    scenario = resolve_scenario_param(request, workspace)
    is_alternative_scenario = scenario.scenario_type == ScenarioType.ALTERNATIVE
    canvas_view_name: str | None = None
    paintable_column_meta: list[dict[str, str]] = []
    built_forms_data: dict[str, list[dict[str, object]]] = {}
    paint_url: str = ""
    clear_url: str = ""
    grid_url: str = ""
    merge_url: str = ""
    bf_paint_url: str = ""
    bf_match_url: str = ""
    bf_fill_url: str = ""
    history_url: str = ""
    undo_url: str = ""

    if is_alternative_scenario:
        # Build canvas view source (the COALESCE view for this scenario)
        schema, view_name = scenario.base_layer_source()
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
        # is always live (it is a view over workspace_paintedcanvas; see
        # services.scenario_canvas), but the *browser* doesn't know that.
        # Stamp the tile URL with the most recent paint write for this
        # scenario so a repaint always changes the URL (and therefore the
        # browser's cache key), the same way brew-gis-map.ts's
        # refreshCanvasTiles() cache-busts mid-session.
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
        grid_url = request.build_absolute_uri(
            reverse("workspace:grid_parcels", args=[workspace_pk, scenario.pk])
        )
        merge_url = request.build_absolute_uri(
            reverse("workspace:merge_parcels", args=[workspace_pk, scenario.pk])
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

    # Build regular layer data. Scoped to the active scenario: a scenario's
    # analysis results belong to it alone (each scenario owns an instance of
    # every analysis model), so rendering another scenario's results here
    # would draw the same analysis several times over, from data that isn't
    # this scenario's.
    layers = visible_layers_for_panel(workspace, scenario)
    layer_data = []
    for layer in layers:
        is_painted_features_layer = layer.key == PAINTED_FEATURES_LAYER_KEY
        if is_painted_features_layer and not is_alternative_scenario:
            # This overlay has no source of its own — it only ever renders
            # against the active ALTERNATIVE scenario's canvas view (below).
            # Without one there's nothing to tile from, so skip it entirely
            # rather than fall through to to_maplibre_source() with no
            # db_table.
            continue

        data = LayerSchema.model_validate(layer).model_dump()
        data["id"] = layer.key
        data["type"] = layer.geometry_type
        is_base_layer = layer.key == BASE_CANVAS_LAYER_KEY

        if (is_base_layer or is_painted_features_layer) and is_alternative_scenario:
            # A scenario is active: tile this layer from the scenario's
            # canvas view (base canvas COALESCEd with any PaintedCanvas
            # overrides) instead of the raw, unpainted base table — so the
            # symbology below (breaks/colors/categories) actually reflects
            # painted values instead of silently showing stale data.
            data["source"] = {
                "type": "vector",
                "tiles": [canvas_tiles_url],
                "promoteId": "parcel_id",
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
                data["source"]["promoteId"] = "parcel_id"
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

        # Merge symbology-generated paint/layout if available. The attribute
        # column driving it is also surfaced to the frontend so hover
        # tooltips can show just the column(s) actually used for styling
        # (e.g. built_form_key, vmt_total) instead of every column on the
        # layer's table.
        data["name"] = layer.name
        data["attribute_column"] = ""
        data["attribute_label"] = ""
        try:
            config = layer.symbology
            style = generate_maplibre_style(config)
            data["paint"] = style["paint"]
            data["layout"] = style["layout"]
            if config.attribute_column:
                data["attribute_column"] = config.attribute_column
                data["attribute_label"] = _resolve_attribute_label(
                    config.attribute_column
                )
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
    canvas_view_layer_id = PAINTED_FEATURES_LAYER_KEY if is_alternative_scenario else ""
    selection_mode = request.GET.get("selection_mode", "click")

    # Layer id to click-inspect against when no scenario is active. Only
    # set if the workspace's base table has actually been registered as a
    # Layer — nothing does that automatically today, so inspect click is
    # effectively scenario-only otherwise.
    base_layer_id = ""
    for layer in layers:
        if layer.key == BASE_CANVAS_LAYER_KEY:
            base_layer_id = layer.key
            break

    # Build URL for the map page with scenario param
    scenario_url = ""
    if is_alternative_scenario:
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
        "viewport_json": json.dumps(
            _query_viewport(request) or _resolve_viewport(workspace)
        ),
        "workspace": workspace,
        "scenario": scenario,
        "is_alternative_scenario": is_alternative_scenario,
        "scenario_json": json.dumps(
            {"id": scenario.pk, "name": scenario.name, "slug": scenario.slug}
        )
        if is_alternative_scenario
        else "null",
        "scenario_url": scenario_url,
        "canvas_view_name": canvas_view_name or "",
        "paintable_columns": paintable_column_meta,
        "built_forms": built_forms_data,
        "paint_url": paint_url,
        "clear_url": clear_url,
        "grid_url": grid_url,
        "merge_url": merge_url,
        "bf_paint_url": bf_paint_url,
        "bf_match_url": bf_match_url,
        "bf_fill_url": bf_fill_url,
        "history_url": history_url if is_alternative_scenario else "",
        "undo_url": undo_url if is_alternative_scenario else "",
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

    layers = visible_layers_for_panel(workspace, scenario).order_by("display_order")

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
        # Without this the template's ``viewport=''`` leaves the component's
        # viewport null, and MapLibre opens on the whole world at Null Island
        # instead of the scenario's own geography.
        "viewport_json": json.dumps(
            _query_viewport(request) or _resolve_viewport(workspace)
        ),
        "scenario": scenario,
        "is_public_view": True,
        "disable_paint": True,
        "public_token": token,
    }

    return render(request, "workspace_map.html", context)
