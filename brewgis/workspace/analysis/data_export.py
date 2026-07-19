"""Export Django model data to PostGIS tables for SQLMesh consumption.

Bridge between the Django ORM world (BuildingType records stored in
``public.workspace_buildingtype``) and the SQLMesh analysis pipeline
which expects flat, de-normalized tables with specific column names.

The main consumer is the core_end_state SQLMesh model, which joins parcels
against a built_forms table using columns like ``du_per_acre``,
``emp_per_acre``, ``far``, etc. — matching the BuildingType model fields.
"""
# ruff: noqa: S608 — schema/table names cannot be SQL bind parameters

from __future__ import annotations

import logging
from typing import Any

from django.db import connection
from django.db import transaction

logger = logging.getLogger(__name__)

# Columns exported from workspace_buildingtype → built_forms table.
# Maps SQLMesh-expected column → BuildingType model field name (or SQL expression).
BUILT_FORM_COLUMNS: dict[str, str] = {
    "id": "id",
    "key": "name",
    "du_per_acre": "du_per_acre",
    "emp_per_acre": "emp_per_acre",
    "far": "far",
    "household_size": "household_size",
    "vacancy_rate": "vacancy_rate",
    "jobs_by_sector": "jobs_by_sector::text::jsonb",
    "indoor_water_rate": "indoor_water_rate",
    "outdoor_water_rate": "outdoor_water_rate",
    "irrigable_area_fraction": "irrigable_area_fraction",
    "building_coverage": "building_coverage",
    "electricity_eui": "electricity_eui",
    "gas_eui": "gas_eui",
    "vintage": "vintage",
    "trip_rate_override": "trip_rate_override",
    "ite_land_use_code": "ite_land_use_code",
    "pass_by_trip_pct": "pass_by_trip_pct",
}

# Columns that need a COALESCE wrapper so None becomes 0 in the output table
_NULLABLE_TO_ZERO: set[str] = {
    "du_per_acre",
    "emp_per_acre",
    "far",
    "indoor_water_rate",
    "outdoor_water_rate",
    "irrigable_area_fraction",
    "building_coverage",
    "electricity_eui",
    "gas_eui",
    "trip_rate_override",
}

_BOOL_COLUMNS: set[str] = set()
_JSON_COLUMNS: set[str] = {"jobs_by_sector"}


def _column_defs(field_map: dict[str, str]) -> str:
    """Build the column list for CREATE TABLE / INSERT statements.

    Wraps nullable float columns in COALESCE(…, 0) so the output table
    never contains NULL for density/rate columns the SQLMesh model expects
    to be non-null.
    """
    parts: list[str] = []
    for out_name, source_expr in field_map.items():
        if out_name in _NULLABLE_TO_ZERO:
            parts.append(f"COALESCE({source_expr}, 0.0) AS {out_name}")
        else:
            parts.append(f"{source_expr} AS {out_name}")
    return ",\n                ".join(parts)


@transaction.atomic
def export_building_types(
    schema: str = "public",
    table: str = "built_forms",
    *,
    force_recreate: bool = False,
) -> int:
    """Export BuildingType records from Django ORM to a flat PostGIS table.

    Creates (or re-creates) ``{schema}.{table}`` with the columns listed
    in :py:data:`BUILT_FORM_COLUMNS`.  All BuildingType rows are copied
    into the target table.

    Args:
        schema: Target PostGIS schema.
        table: Target table name.
        force_recreate: If True, DROP and recreate from scratch
            (instead of TRUNCATE + INSERT).

    Returns:
        Number of rows inserted.

    Raises:
        RuntimeError: If the source Django table *workspace_buildingtype*
            does not exist or has no rows (table may not be migrated).
    """
    with connection.cursor() as cursor:
        # Verify the source table exists and has data
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'workspace_buildingtype'"
        )
        if cursor.fetchone()[0] == 0:
            msg = "Source table 'public.workspace_buildingtype' not found — has the migration been run?"
            raise RuntimeError(msg)

        cursor.execute("SELECT COUNT(*) FROM public.workspace_buildingtype")
        row_count = cursor.fetchone()[0]
        if row_count == 0:
            logger.warning(
                "No BuildingType records found — export will produce an empty table."
            )

        cols = _column_defs(BUILT_FORM_COLUMNS)
        source_table = "public.workspace_buildingtype"

        if force_recreate:
            cursor.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
            cursor.execute(
                f"""
                CREATE TABLE "{schema}"."{table}" AS
                SELECT {cols}
                FROM {source_table}
                WITH NO DATA
                """
            )
        else:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{schema}"."{table}" AS
                SELECT {cols}
                FROM {source_table}
                WITH NO DATA
                """
            )

        cursor.execute(f'TRUNCATE TABLE "{schema}"."{table}"')
        cursor.execute(
            f"""
            INSERT INTO "{schema}"."{table}"
            SELECT {cols}
            FROM {source_table}
            """
        )
    return row_count  # type: ignore[no-any-return]


def ensure_export_exists(
    schema: str = "public",
    table: str = "built_forms",
    **kwargs: Any,
) -> int:
    """Idempotent export wrapper — only exports if the target table is empty.

    Useful when the export is called before every pipeline run and the
    data hasn't changed (e.g. during development).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            [schema, table],
        )
        exists = cursor.fetchone()[0] > 0

        if exists:
            cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            count = cursor.fetchone()[0]
            if count > 0:
                logger.info(
                    "Export table %s.%s already exists with %d rows — skipping",
                    schema,
                    table,
                    count,
                )
                return count  # type: ignore[no-any-return]

    return export_building_types(schema, table, **kwargs)
