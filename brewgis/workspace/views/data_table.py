"""View for displaying layer data as a paginated/sortable HTML table."""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import connection
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_GET

from brewgis.workspace.analysis.layer_registry import BASE_CANVAS_LAYER_KEY
from brewgis.workspace.models import Layer
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
    if layer.key == BASE_CANVAS_LAYER_KEY:
        schema, table = scenario.base_layer_source()
    else:
        schema = layer.db_schema or workspace.db_schema
        table = layer.db_table

    quoted_schema = connection.ops.quote_name(schema)
    quoted_table = connection.ops.quote_name(table)

    with connection.cursor() as cursor:
        # ── Column metadata ──────────────────────────────────────────
        cursor.execute(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            [schema, table],
        )
        all_columns = cursor.fetchall()
        all_column_names = [col_name for col_name, _ in all_columns]

        non_geom_columns = [
            col_name
            for col_name, udt_name in all_columns
            if udt_name not in _POSTGIS_TYPES
        ]
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

        # Determine feature ID column for row-click highlight
        feature_id_column: str | None = None
        id_candidates = ["__gid", "gid", "fid", "id", "ogc_fid"]
        for c in id_candidates:
            if c in all_column_names:
                feature_id_column = c
                break
        if not feature_id_column and data_columns:
            feature_id_column = data_columns[0]

        if data_columns:
            quoted_cols = ", ".join(connection.ops.quote_name(c) for c in data_columns)
            cursor.execute(
                f"SELECT {quoted_cols} FROM {quoted_schema}.{quoted_table} "
                f"{order_clause} LIMIT %s OFFSET %s",
                [page_size, offset],
            )
            for db_row in cursor.fetchall():
                row_values = [str(v) if v is not None else "" for v in db_row]
                # Prepend feature_id as first column (hidden, used for row-click)
                rows.append(row_values)

    # Determine feature_id_col_index for the template (0-based position in the row)
    feature_id_col_index: int | None = None
    if feature_id_column and feature_id_column in all_column_names:
        # Map the column name to index in the raw all_column_names list
        feature_id_col_index = all_column_names.index(feature_id_column)

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
