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

from brewgis.workspace.models import Layer

logger = logging.getLogger(__name__)

_POSTGIS_TYPES = {"geometry", "geography"}
_MAX_VISIBLE_COLUMNS = 20
_DEFAULT_PAGE_SIZE = 50


@user_passes_test(lambda u: u.is_authenticated)
@require_GET
def layer_data_table(request: HttpRequest, layer_pk: int) -> HttpResponse:
    """Render a paginated, sortable HTML table of layer data.

    Fetches non-spatial columns directly from PostGIS, supports column
    sorting and cursor-based pagination via htmx.
    """
    layer = get_object_or_404(Layer, pk=layer_pk)
    schema = layer.workspace.db_schema
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

        data_columns: list[str] = []
        for col_name, udt_name in all_columns:
            if udt_name in _POSTGIS_TYPES:
                continue
            data_columns.append(col_name)
            if len(data_columns) >= _MAX_VISIBLE_COLUMNS:
                break

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

    context: dict[str, Any] = {
        "layer": layer,
        "columns": data_columns,
        "rows": rows,
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
