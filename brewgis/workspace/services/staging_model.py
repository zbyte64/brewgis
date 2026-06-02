"""dbt staging model generator — creates SQL views wrapping imported tables.

Generates two types of staging models:

1. **Parcel staging model** (``stage_<table>.sql``): normalizes an imported
   GIS table by mapping the detected ID column to ``parcel_id``/``id`` and
   supplying defaults for columns the dbt pipeline requires.

2. **Base canvas stub** (``stage_<table>_base_canvas.sql``): produces all-zero
   base canvas rows matching the parcel table, so the ``core_increment`` model
   can compute deltas without a real base canvas import.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

if TYPE_CHECKING:
    from brewgis.workspace.services.column_inspector import TableColumnInfo

_STAGING_DIR = Path("brewgis/sqlmesh/models/staging")

# Default built_form_key for parcels without one (2 = "SFR Standard").
_DEFAULT_BUILT_FORM_KEY = 2


def _geom_column(info: TableColumnInfo) -> str:
    """Return the geometry column name present in the table."""
    if info.has_geom:
        if "geom" in info.columns:
            return "geom"
        if "geometry" in info.columns:
            return "geometry"
        for col in info.columns:
            if col.lower() in ("geom", "geometry"):
                return col
    return "geom"


def generate_parcel_staging(
    _schema: str,
    table_name: str,
    info: TableColumnInfo,
) -> str:
    """Generate the dbt staging SQL for an imported parcel table.

    The staging model normalizes column names, maps the detected ID column,
    and supplies defaults for missing required columns.

    Returns the SQL string.
    """
    id_col = info.id_column or "id"
    geom_col = _geom_column(info)

    lines: list[str] = []
    lines.append("{{ config(materialized='view') }}")
    lines.append("")
    lines.append("WITH raw AS (")
    lines.append(
        "    SELECT * FROM {{ var('source_schema', 'public') }}"
        ".{{ var('raw_table', '" + table_name + "') }}"
    )
    lines.append(")")
    lines.append("SELECT")
    lines.append("")
    lines.append("    -- Map detected ID column to parcel_id and id")
    lines.append(f"    {id_col} AS parcel_id,")
    lines.append(f"    {id_col} AS id,")

    # built_form_key
    if info.has_built_form_key:
        lines.append("    built_form_key,")
    else:
        lines.append(
            f"    {_DEFAULT_BUILT_FORM_KEY} AS built_form_key,  -- SFR Standard default"
        )

    # intersection_density — compute from geometry if missing
    if info.has_intersection_density:
        lines.append("    intersection_density,")
    else:
        lines.append("    CASE")
        lines.append("        WHEN ST_Area(" + geom_col + ") / 4046.86 > 0")
        lines.append(
            "            THEN LEAST(25.0,"
            " GREATEST(0.5,"
            " 10.0 / SQRT(ST_Area(" + geom_col + ") / 4046.86)))"
        )
        lines.append("        ELSE 0.5")
        lines.append("    END AS intersection_density,")

    # land_development_category
    if info.has_land_development_category:
        lines.append("    land_development_category,")
    else:
        lines.append("    'standard' AS land_development_category,")

    # geometry
    lines.append(f"    {geom_col} AS geom,")

    # Pass through all other columns (excluding the ones already handled)
    excluded = {
        id_col,
        "parcel_id",
        "id",
        "built_form_key",
        "intersection_density",
        "land_development_category",
        geom_col,
        "geom",
    }
    used_lower = {c.lower() for c in excluded}
    other_cols = [col for col in info.columns if col.lower() not in used_lower]
    for i, col in enumerate(other_cols):
        suffix = "," if i < len(other_cols) - 1 else ""
        lines.append(f"    {col}{suffix}")

    lines.append("FROM raw")
    lines.append("")

    return "\n".join(lines)


def _base_canvas_column_names() -> list[str]:
    """Return the list of base canvas column names in DDL order."""
    return list(BaseCanvasSchema.COLUMN_NAMES)


def generate_base_canvas_stub(
    _schema: str,
    table_name: str,
    info: TableColumnInfo,
) -> str:
    """Generate a dbt model producing a zero-filled base canvas.

    The stub supplies all 77+ base canvas columns with zero defaults,
    so ``core_increment`` computes ``end_state - 0 = end_state``.

    Returns the SQL string.
    """
    id_col = info.id_column or "id"
    geom_col = _geom_column(info)

    lines: list[str] = []
    lines.append("{{ config(materialized='view') }}")
    lines.append("")
    lines.append("SELECT")
    lines.append(f"    {id_col} AS parcel_id,")
    lines.append(f"    {id_col} AS id,")
    lines.append("    NULL::VARCHAR(64) AS id_source,")
    lines.append("    NULL::VARCHAR(128) AS geometry_key,")
    lines.append(f"    {geom_col} AS geometry,")

    if info.has_land_development_category:
        lines.append("    land_development_category,")
    else:
        lines.append("    'standard' AS land_development_category,")

    if info.has_built_form_key:
        lines.append("    built_form_key,")
    else:
        lines.append(f"    {_DEFAULT_BUILT_FORM_KEY} AS built_form_key,")

    if info.has_intersection_density:
        lines.append("    intersection_density,")
    else:
        lines.append("    CASE")
        lines.append("        WHEN ST_Area(" + geom_col + ") / 4046.86 > 0")
        lines.append(
            "            THEN LEAST(25.0,"
            " GREATEST(0.5,"
            " 10.0 / SQRT(ST_Area(" + geom_col + ") / 4046.86)))"
        )
        lines.append("        ELSE 0.5")
        lines.append("    END AS intersection_density,")

    lines.append("    ST_Area(" + geom_col + ") / 4046.86 AS area_gross,")

    # Zero out all remaining numeric base canvas columns
    skip = {
        "id",
        "id_source",
        "geometry_key",
        "geometry",
        "land_development_category",
        "built_form_key",
        "intersection_density",
        "area_gross",
    }
    numeric_cols = [c for c in _base_canvas_column_names() if c not in skip]
    for i, col in enumerate(numeric_cols):
        suffix = "," if i < len(numeric_cols) - 1 else ""
        lines.append(f"    0.0 AS {col}{suffix}")

    lines.append(
        "FROM {{ var('source_schema', 'public') }}"
        ".{{ var('raw_table', '" + table_name + "') }}"
    )
    lines.append("")

    return "\n".join(lines)


def write_parcel_staging(
    schema: str,
    table_name: str,
    info: TableColumnInfo,
) -> str:
    """Generate and write the parcel staging model to disk.

    Returns the filename written (e.g. ``stage_parcels.sql``).
    """
    _STAGING_DIR.mkdir(parents=True, exist_ok=True)
    sql = generate_parcel_staging(schema, table_name, info)
    filename = f"stage_{table_name}.sql"
    path = _STAGING_DIR / filename
    path.write_text(
        "{# AUTO-GENERATED -- do not edit #}\n" + sql + "\n",
    )
    return filename


def write_base_canvas_stub(
    schema: str,
    table_name: str,
    info: TableColumnInfo,
) -> str:
    """Generate and write the base canvas stub model to disk.

    Returns the filename written (e.g. ``stage_parcels_base_canvas.sql``).
    """
    _STAGING_DIR.mkdir(parents=True, exist_ok=True)
    sql = generate_base_canvas_stub(schema, table_name, info)
    filename = f"stage_{table_name}_base_canvas.sql"
    path = _STAGING_DIR / filename
    path.write_text(
        "{# AUTO-GENERATED -- do not edit #}\n" + sql + "\n",
    )
    return filename
