"""View for displaying layer data as a paginated/sortable HTML table."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db import connection
from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.models import Layer
from brewgis.workspace.models import Scenario
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS
from brewgis.workspace.views.panels import resolve_scenario_param

logger = logging.getLogger(__name__)

_POSTGIS_TYPES = {"geometry", "geography"}
_MAX_VISIBLE_COLUMNS = 20
"""Cap on *non-paintable* columns shown. Paintable columns (du, built_form_key,
etc.) are always shown in full regardless of this cap — capping them would
silently hide the very values a paint operation just changed, on a wide
canvas view (see canvas_view_manager.py) where they can fall well past
column 20."""
_DEFAULT_PAGE_SIZE = 50

_FEATURE_ID_CANDIDATES = ("parcel_id", "__gid", "gid", "fid", "id", "ogc_fid")
"""Column names tried in order for a row's feature identifier. ``parcel_id``
is first because that is the id the base canvas and every scenario canvas
view promote into their vector tiles (see ``promoteId`` in views/map.py), so
a located row maps onto the same feature the map draws and highlights."""

_INTEGRAL_UDT_NAMES = {"int2", "int4", "int8"}
_NUMERIC_UDT_NAMES = _INTEGRAL_UDT_NAMES | {"numeric", "float4", "float8"}


def _layer_source(layer: Layer, scenario: Scenario) -> tuple[str, str]:
    """Return the ``(schema, table)`` a layer's rows are read from.

    The base canvas layer is read from the active scenario's own source (its
    painted-aware canvas view when the scenario is an alternative one), every
    other layer from its own backing table.
    """
    if layer.key == BASE_CANVAS_LAYER_KEY:
        return scenario.base_layer_source()
    return layer.db_schema or layer.workspace.db_schema, layer.db_table


def _table_columns(schema: str, table: str) -> list[tuple[str, str]]:
    """Return ``(column_name, udt_name)`` for a table, in table order."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema, table],
        )
        return [(str(name), str(udt)) for name, udt in cursor.fetchall()]


def _feature_id_column(all_column_names: list[str]) -> str | None:
    """Return the column identifying one row of *all_column_names*.

    Falls back to the first column for tables with none of the usual
    identifier names (e.g. an imported CSV with only attributes) — a wrong
    guess degrades a locate to "no such feature", it never picks a column
    that another row could share.
    """
    for candidate in _FEATURE_ID_CANDIDATES:
        if candidate in all_column_names:
            return candidate
    return all_column_names[0] if all_column_names else None


def _coerce_feature_id(raw: str, udt_name: str) -> int | float | str:
    """Convert a feature id from the query string to its column's own type.

    Postgres won't cast a text parameter to an integer column on its own, and
    comparing a *text* column against a number would drop the index, so the
    value is shaped to match the column instead.
    """
    if udt_name in _NUMERIC_UDT_NAMES:
        if udt_name in _INTEGRAL_UDT_NAMES:
            return int(raw)
        return float(raw)
    return raw


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_data_table(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Render a paginated, sortable HTML table of layer data.

    Fetches non-spatial columns directly from PostGIS, supports column
    sorting and cursor-based pagination via htmx.
    """
    layer = get_object_or_404(Layer, pk=layer_pk)
    workspace = layer.workspace
    scenario = resolve_scenario_param(request, workspace)
    schema, table = _layer_source(layer, scenario)

    quoted_schema = connection.ops.quote_name(schema)
    quoted_table = connection.ops.quote_name(table)

    with connection.cursor() as cursor:
        # ── Column metadata ──────────────────────────────────────────
        all_columns = _table_columns(schema, table)

        non_geom_columns = [
            col_name
            for col_name, udt_name in all_columns
            if udt_name not in _POSTGIS_TYPES
        ]
        feature_id_column = _feature_id_column(non_geom_columns)
        # Fill the cap from non-paintable columns first, then always add
        # every paintable column present — see _MAX_VISIBLE_COLUMNS above.
        selected: set[str] = set()
        for col_name in non_geom_columns:
            if col_name in PAINTABLE_COLUMNS:
                continue
            if len(selected) >= _MAX_VISIBLE_COLUMNS:
                break
            selected.add(col_name)
        selected.update(c for c in non_geom_columns if c in PAINTABLE_COLUMNS)
        # The feature id column is force-included too: past the cap it would
        # otherwise be dropped, and every row's locate button — and the row's
        # own click-to-highlight — reads its value by index from the row.
        if feature_id_column:
            selected.add(feature_id_column)

        # Preserve the table's natural left-to-right column order.
        data_columns = [c for c in non_geom_columns if c in selected]

        # ── Count ────────────────────────────────────────────────────
        count_sql = f"SELECT COUNT(*) FROM {quoted_schema}.{quoted_table}"
        cursor.execute(count_sql)
        total_rows = cursor.fetchone()[0]

        # ── Sort ─────────────────────────────────────────────────────
        sort_raw = request.GET.get("sort", "")
        sort_desc = sort_raw.startswith("-")
        sort_field = sort_raw[1:] if sort_desc else sort_raw
        if sort_field not in data_columns:
            sort_field = ""
            sort_raw = ""

        order_clause = ""
        if sort_field:
            direction = "DESC" if sort_desc else "ASC"
            order_clause = (
                f"ORDER BY {connection.ops.quote_name(sort_field)} {direction}"
            )

        # ── Pagination ───────────────────────────────────────────────
        try:
            page_size = int(request.GET.get("page_size", _DEFAULT_PAGE_SIZE))
        except (ValueError, TypeError):
            page_size = _DEFAULT_PAGE_SIZE
        page_size = max(1, min(page_size, 250))

        try:
            page_number = int(request.GET.get("page", 1))
        except (ValueError, TypeError):
            page_number = 1
        page_number = max(1, page_number)

        paginator = Paginator(range(total_rows), page_size)
        page_obj = paginator.get_page(page_number)
        offset = (page_number - 1) * page_size

        # ── Data rows ────────────────────────────────────────────────
        rows: list[list[str]] = []

        if data_columns:
            quoted_cols = ", ".join(connection.ops.quote_name(c) for c in data_columns)
            cursor.execute(
                f"SELECT {quoted_cols} FROM {quoted_schema}.{quoted_table} "
                f"{order_clause} LIMIT %s OFFSET %s",
                [page_size, offset],
            )
            for db_row in cursor.fetchall():
                rows.append([str(v) if v is not None else "" for v in db_row])

    # Position of the feature id within a *rendered row*, which is not its
    # position in the table: rows carry only the visible columns, so a
    # column dropped by the cap would shift every index after it and hand the
    # template a neighbouring column's value instead of the id.
    feature_id_col_index: int | None = None
    if feature_id_column and feature_id_column in data_columns:
        feature_id_col_index = data_columns.index(feature_id_column)

    context: dict[str, Any] = {
        "layer": layer,
        "scenario": scenario,
        "columns": data_columns,
        "rows": rows,
        "feature_id_column": feature_id_column,
        "feature_id_col_index": feature_id_col_index,
        "total_rows": total_rows,
        "column_count": len(data_columns),
        "page_obj": page_obj,
        "paginator": paginator,
        "sort_field": sort_field,
        "sort_desc": sort_desc,
        "sort_raw": sort_raw,
        "page_size": page_size,
    }

    return render(request, "workspace/partials/_data_table.html", context)


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_feature_bounds(request: HttpRequest, layer_pk: int) -> JsonResponse:
    """Return one feature's geometry and bounding box, both in EPSG:4326.

    Answers the data table's "Locate on map" button: ``bounds`` is what the map
    fits, ``geometry`` is the GeoJSON outline it draws over the feature — the
    way a located row of a point layer (a POI's circle) gets marked, since
    feature-state highlighting only reaches the active parcel source. Both are
    read straight from the layer's own table rather than from the map's loaded
    vector tiles: the client can only query features the current viewport has
    already fetched, so a row for a parcel a page away — or anywhere off-screen
    — would find nothing to zoom to.
    """
    layer = get_object_or_404(Layer, pk=layer_pk)
    workspace = layer.workspace
    scenario = resolve_scenario_param(request, workspace)
    feature_id = request.GET.get("feature_id", "")
    if not feature_id:
        return JsonResponse({"error": "feature_id is required"}, status=400)

    schema, table = _layer_source(layer, scenario)
    all_columns = _table_columns(schema, table)
    geometry_column = next(
        (name for name, udt in all_columns if udt in _POSTGIS_TYPES), None
    )
    non_geom_columns = [name for name, udt in all_columns if udt not in _POSTGIS_TYPES]
    # The same column the data table labelled the row with — including its
    # first-non-geometry fallback, so both ends agree on what a row's id is.
    feature_id_column = _feature_id_column(non_geom_columns)
    if geometry_column is None or feature_id_column is None:
        return JsonResponse({"error": "Layer has no locatable geometry"}, status=400)

    feature_id_type = dict(all_columns)[feature_id_column]
    try:
        feature_id_value = _coerce_feature_id(feature_id, feature_id_type)
    except ValueError:
        return JsonResponse({"error": f"No feature {feature_id!r}"}, status=404)

    quote = connection.ops.quote_name
    # Its own savepoint: an unreadable geometry (a table whose geometry has no
    # SRID, say) must not abort the request's transaction and take the rest of
    # the page's queries down with it. One row, one query: the bounds and the
    # outline are the same geometry. 6 decimal places is ~0.1 m — the overlay
    # is drawn at screen resolution, and a whole parcel's coordinates at the
    # default 9 would be several times the payload.
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "WITH located AS ("  # noqa: S608
                f"SELECT ST_Transform({quote(geometry_column)}, 4326) AS geom "
                f"FROM {quote(schema)}.{quote(table)} "
                f"WHERE {quote(feature_id_column)} = %s LIMIT 1) "
                "SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom), "
                "ST_AsGeoJSON(geom, 6) FROM located",
                [feature_id_value],
            )
            row = cursor.fetchone()
    except DatabaseError:
        logger.warning(
            "Could not read feature geometry for layer %s", layer_pk, exc_info=True
        )
        return JsonResponse({"error": "Feature geometry could not be read"}, status=400)

    if not row or row[0] is None:
        return JsonResponse({"error": f"No feature {feature_id!r}"}, status=404)

    min_lng, min_lat, max_lng, max_lat = (float(value) for value in row[:4])
    geometry: Any = json.loads(row[4]) if row[4] is not None else None
    return JsonResponse(
        {"bounds": [[min_lng, min_lat], [max_lng, max_lat]], "geometry": geometry}
    )
