"""Auto-registration of analysis result views as Layer objects.

After a successful SQLMesh plan, materialized views are created in PostGIS.
This module creates or updates corresponding Layer objects in the workspace
so the results are discoverable by the tile server and map component.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection

from brewgis.workspace.analysis.module_registry import get_primary_column
from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)

BASE_CANVAS_LAYER_KEY = "base_canvas"
"""Stable Layer.key for a workspace's base canvas layer.

Fixed (not derived from the table name) so that switching
``Workspace.base_table`` to a different table updates this same Layer in
place instead of leaving the old one orphaned in the Layers panel.
"""


def _get_table_columns(schema: str, table: str) -> list[dict[str, Any]]:
    """Introspect column metadata from PostGIS for a given table/view.

    Returns a list of dicts with keys: column_name, data_type, numeric.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.column_name,
                c.data_type,
                CASE WHEN c.data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision')
                     THEN true ELSE false END AS is_numeric
            FROM information_schema.columns c
            WHERE c.table_schema = %s
              AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            [schema, table],
        )
        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "numeric": row[2],
            }
            for row in cursor.fetchall()
        ]


def _classify_geometry_type_name(geom_type: str) -> str | None:
    """Map a PostGIS geometry type name to a Layer geometry_type.

    Accepts names in either ``geometry_columns.type`` form ("POLYGON",
    "MULTILINESTRING") or ``ST_GeometryType()`` form ("ST_Polygon",
    "ST_MultiPoint"). Returns None for generic/unrecognized names (e.g. the
    bare "geometry" type PostGIS reports for many computed view columns), so
    callers can fall back to inspecting actual row data instead of guessing.
    """
    lowered = geom_type.lower()
    if "polygon" in lowered:
        return "fill"
    if "line" in lowered:
        return "line"
    if "point" in lowered:
        return "circle"
    return None


def _get_geometry_type(schema: str, table: str) -> str:
    """Determine the geometry type of a PostGIS table/view.

    Returns: "fill", "line", or "circle".

    ``geometry_columns.type`` is frequently just "GEOMETRY" for computed or
    view-based geometry columns (PostGIS can't statically infer a specific
    subtype), which would otherwise fall through to a wrong guess. When that
    happens, this samples one row's actual geometry via ``ST_GeometryType``
    instead of assuming.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f_geometry_column, type
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
            """,
            [schema, table],
        )
        row = cursor.fetchone()
        if not row:
            return "fill"

        geom_column, catalog_type = row
        classified = _classify_geometry_type_name(catalog_type)
        if classified is not None:
            return classified

        cursor.execute(
            f"""
            SELECT ST_GeometryType({connection.ops.quote_name(geom_column)})
            FROM {connection.ops.quote_name(schema)}.{connection.ops.quote_name(table)}
            WHERE {connection.ops.quote_name(geom_column)} IS NOT NULL
            LIMIT 1
            """  # noqa: S608 -- schema/table/column are catalog-sourced, not user input
        )
        sample = cursor.fetchone()
        if sample:
            classified = _classify_geometry_type_name(sample[0])
            if classified is not None:
                return classified
        return "fill"


def _find_numeric_column(columns: list[dict[str, Any]], table: str) -> str | None:
    """Find the numeric column that best represents this result table.

    Prefers the analysis module's known headline output column (see
    ``module_registry.TABLE_PRIMARY_COLUMN``), then falls back to a handful
    of common cross-module names like 'population'/'households', and only
    then to the first numeric column that isn't an id or geometry column.
    """
    numeric_columns = {col["column_name"] for col in columns if col["numeric"]}
    primary_column = get_primary_column(table)
    if primary_column and primary_column in numeric_columns:
        return primary_column

    preferred = {
        "acres_developable",
        "developable_proportion",
        "population",
        "households",
        "dwelling_units_total",
        "employment_total",
        "employment",
        "total_population",
        "total_households",
    }
    for col in columns:
        if col["numeric"] and col["column_name"] in preferred:
            return col["column_name"]  # type: ignore[no-any-return]

    # Fallback: first numeric column that looks like a data column
    skip_patterns = {"id", "pk", "parcel_id", "geom"}
    for col in columns:
        if col["numeric"] and col["column_name"] not in skip_patterns:
            return col["column_name"]  # type: ignore[no-any-return]

    return None


def register_result_layer(
    workspace_id: int,
    schema: str,
    table: str,
    *,
    name: str | None = None,
    description: str | None = None,
    key: str | None = None,
) -> Layer | None:
    """Register a PostGIS view/table as a Layer in the workspace.

    Creates a new Layer or updates an existing one. Also creates an
    auto-generated SymbologyConfig if the Layer is new.

    Args:
        workspace_id: Workspace primary key.
        schema: PostGIS schema containing the table.
        table: PostGIS table/view name.
        name: Human-readable layer name (auto-generated if None).
        description: Layer description.
        key: Explicit Layer key. Defaults to the table name. Pass a stable
            key (e.g. ``"base_canvas"``) when the underlying table can change
            over time and re-registration should update the same Layer
            rather than create a new one per table name.

    Returns:
        The Layer instance, or None if registration fails.
    """
    try:
        workspace = Workspace.objects.get(pk=workspace_id)
    except Workspace.DoesNotExist:
        logger.error("Workspace %s not found, cannot register layer", workspace_id)
        return None

    # Determine geometry type
    geometry_type = _get_geometry_type(schema, table)

    # Generate human-readable name
    layer_name = name or table.replace("_", " ").title()

    # Look up columns for auto-configuration
    columns = _get_table_columns(schema, table)
    numeric_column = _find_numeric_column(columns, table)

    # Create or update the Layer
    layer_key = key or table

    layer, created = Layer.objects.update_or_create(
        workspace=workspace,
        key=layer_key,
        defaults={
            "name": layer_name,
            "description": description or f"Analysis result: {table}",
            "layer_source": "postgis",
            "db_table": table,
            "db_schema": schema,
            "geometry_type": geometry_type,
        },
    )

    logger.info(
        "%s Layer '%s' (key=%s) in workspace %s",
        "Created" if created else "Updated",
        layer_name,
        layer_key,
        workspace_id,
    )

    # Auto-generate symbology for new layers. Also backfill it for an
    # existing layer whose config was never customized and never got past
    # the bare defaults (symbology_type="single", attribute_column="") —
    # e.g. one first registered against a table that didn't exist yet
    # (a stale schema/table pointer), where numeric_column was None back
    # then and this never ran. A config the user has actually touched
    # (auto_generated=False) or a previously-successful auto-config is
    # left untouched either way.
    existing_config = SymbologyConfig.objects.filter(layer=layer).first()
    needs_auto_config = existing_config is None or (
        existing_config.auto_generated and not existing_config.attribute_column
    )
    if numeric_column and (created or needs_auto_config):
        SymbologyConfig.objects.update_or_create(
            layer=layer,
            defaults={
                "symbology_type": "graduated",
                "attribute_column": numeric_column,
                "num_classes": 5,
                "auto_generated": True,
            },
        )
        logger.info(
            "Auto-generated graduated symbology for %s on column %s",
            layer_key,
            numeric_column,
        )

    return layer
