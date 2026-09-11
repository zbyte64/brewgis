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
from typing import TYPE_CHECKING
from typing import Any

import psycopg
from django.conf import settings
from django.db import connection
from django.db import transaction

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace

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


def _export_building_types(
    cursor: Any,
    workspace: Workspace,
    schema: str,
    table: str,
    *,
    force_recreate: bool,
) -> int:
    """Export logic shared by every connection variant — see callers below."""
    # Verify the source table exists
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'workspace_buildingtype'"
    )
    if cursor.fetchone()[0] == 0:
        msg = "Source table 'public.workspace_buildingtype' not found — has the migration been run?"
        raise RuntimeError(msg)

    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    cursor.execute(
        "SELECT COUNT(*) FROM public.workspace_buildingtype WHERE workspace_id = %s",
        [workspace.pk],
    )
    row_count = cursor.fetchone()[0]
    if row_count == 0:
        logger.warning(
            "No BuildingType records found for workspace %s — export will "
            "produce an empty table.",
            workspace.pk,
        )

    cols = _column_defs(BUILT_FORM_COLUMNS)
    source_table = (
        f"(SELECT * FROM public.workspace_buildingtype "
        f"WHERE workspace_id = {workspace.pk}) AS workspace_buildingtype"
    )

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


def _is_already_populated(cursor: Any, schema: str, table: str) -> int | None:
    """Return the row count if {schema}.{table} already exists and is non-empty."""
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s",
        [schema, table],
    )
    if cursor.fetchone()[0] == 0:
        return None
    cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
    count = cursor.fetchone()[0]
    return count or None


def _dsn_from_settings() -> str:
    """Build a libpq connection string from Django's default database settings."""
    db = settings.DATABASES["default"]
    return (
        f"host={db['HOST']} port={db['PORT'] or 5432} dbname={db['NAME']} "
        f"user={db['USER']} password={db['PASSWORD']}"
    )


@transaction.atomic
def export_building_types(
    workspace: Workspace,
    schema: str = "public",
    table: str = "built_forms",
    *,
    force_recreate: bool = False,
) -> int:
    """Export a workspace's BuildingType records to a flat PostGIS table.

    Creates (or re-creates) ``{schema}.{table}`` with the columns listed
    in :py:data:`BUILT_FORM_COLUMNS`, populated only from *workspace*'s own
    BuildingType rows — each workspace has its own building type library.

    Runs on Django's own request-scoped connection — under
    ``ATOMIC_REQUESTS``, the write is only visible to other connections once
    the whole request commits. Use :func:`export_building_types_isolated` when
    something outside this connection (e.g. SQLMesh's own engine adapter)
    needs to see the result before the request finishes.

    Args:
        workspace: The workspace whose BuildingType rows to export.
        schema: Target PostGIS schema.
        table: Target table name.
        force_recreate: If True, DROP and recreate from scratch
            (instead of TRUNCATE + INSERT).

    Returns:
        Number of rows inserted.

    Raises:
        RuntimeError: If the source Django table *workspace_buildingtype*
            does not exist (table may not be migrated).
    """
    with connection.cursor() as cursor:
        return _export_building_types(
            cursor, workspace, schema, table, force_recreate=force_recreate
        )


def export_building_types_isolated(
    workspace: Workspace,
    schema: str = "public",
    table: str = "built_forms",
    *,
    force_recreate: bool = False,
) -> int:
    """Same export as :func:`export_building_types`, on its own connection.

    Opens a dedicated psycopg connection, commits, and closes it — so the
    result is durably visible to any other connection (e.g. SQLMesh's engine
    adapter) immediately, regardless of whether the caller's own Django
    request transaction (``ATOMIC_REQUESTS``) later commits or rolls back.
    """
    conn = psycopg.connect(_dsn_from_settings())
    try:
        with conn.cursor() as cursor:
            row_count = _export_building_types(
                cursor, workspace, schema, table, force_recreate=force_recreate
            )
        conn.commit()
    finally:
        conn.close()
    return row_count


def ensure_export_exists(
    workspace: Workspace,
    schema: str = "public",
    table: str = "built_forms",
    **kwargs: Any,
) -> int:
    """Idempotent export wrapper — only exports if the target table is empty.

    Useful when the export is called before every pipeline run and the
    data hasn't changed (e.g. during development).
    """
    with connection.cursor() as cursor:
        count = _is_already_populated(cursor, schema, table)
        if count is not None:
            logger.info(
                "Export table %s.%s already exists with %d rows — skipping",
                schema,
                table,
                count,
            )
            return count

    return export_building_types(workspace, schema, table, **kwargs)


def ensure_export_exists_isolated(
    workspace: Workspace,
    schema: str = "public",
    table: str = "built_forms",
    **kwargs: Any,
) -> int:
    """Same idempotent check as :func:`ensure_export_exists`, on its own connection.

    See :func:`export_building_types_isolated` — use this from inside a
    request wrapped in ``ATOMIC_REQUESTS`` so the export commits immediately
    instead of waiting on the request's own transaction.
    """
    conn = psycopg.connect(_dsn_from_settings())
    try:
        with conn.cursor() as cursor:
            count = _is_already_populated(cursor, schema, table)
    finally:
        conn.close()
    if count is not None:
        logger.info(
            "Export table %s.%s already exists with %d rows — skipping",
            schema,
            table,
            count,
        )
        return count

    return export_building_types_isolated(workspace, schema, table, **kwargs)
