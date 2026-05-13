"""Auto-registration of analysis result views as Layer objects.

After a successful dbt run, materialized views are created in PostGIS.
This module creates or updates corresponding Layer objects in the workspace
so the results are discoverable by the tile server and map component.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection

from brewgis.workspace.models import Layer
from brewgis.workspace.models import SymbologyConfig
from brewgis.workspace.models import Workspace

logger = logging.getLogger(__name__)


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


def _get_geometry_type(schema: str, table: str) -> str:
    """Determine the geometry type of a PostGIS table/view.

    Returns: "fill", "line", or "circle".
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT type
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
            """,
            [schema, table],
        )
        row = cursor.fetchone()
        if row:
            geom_type = row[0].lower()
            if geom_type in ("polygon", "multipolygon"):
                return "fill"
            if geom_type in ("linestring", "multilinestring"):
                return "line"
        return "fill"


def _find_numeric_column(columns: list[dict[str, Any]]) -> str | None:
    """Find the first numeric column suitable for graduated symbology.

    Prefers columns like 'acres_developable', 'population', 'households',
    'dwelling_units_total', 'employment_total', then falls back to
    the first numeric column that isn't an id or geometry column.
    """
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
    numeric_column = _find_numeric_column(columns)

    # Create or update the Layer
    layer_key = f"{table}"

    layer, created = Layer.objects.update_or_create(
        workspace=workspace,
        key=layer_key,
        defaults={
            "name": layer_name,
            "description": description or f"Analysis result: {table}",
            "layer_source": "postgis",
            "db_table": table,
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

    # Auto-generate symbology for new layers
    if created and numeric_column:
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
