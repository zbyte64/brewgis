"""Pre-analysis validation — checks prerequisites before launching a pipeline run."""
# ruff: noqa: ANN001  -- cursor params are internal helpers

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import connection


@dataclass
class PreflightError:
    """A blocking prerequisite failure."""

    field: str
    message: str


def check_analysis_prerequisites(
    schema: str,
    parcel_table: str,
    base_canvas_table: str | None = None,
    built_form_table: str | None = "built_forms",
) -> list[PreflightError]:
    """Validate that all tables/columns required for an analysis run exist.

    Returns an empty list when all checks pass. Each returned
    ``PreflightError`` describes a single blocking issue.

    Args:
        schema: Database schema containing source tables.
        parcel_table: Parcel table name.
        base_canvas_table: Base canvas table name (or the staging stub).
        built_form_table: Built form (BuildingType) definitions table.

    Returns:
        List of ``PreflightError`` instances, one per failed check.
    """
    errors: list[PreflightError] = []

    with connection.cursor() as cursor:
        # ── 1. Parcel table exists ──────────────────────────────────
        parcel_schema, parcel_name = _split(schema, parcel_table)
        if not _table_exists(cursor, parcel_schema, parcel_name):
            errors.append(
                PreflightError(
                    field="parcel_table",
                    message=f"Table {parcel_schema}.{parcel_name} not found.",
                ),
            )
            return errors  # Cannot proceed without the parcel table

        # ── 2. Parcel table has geometry column ─────────────────────
        lower_cols = {
            c.lower() for c in _get_columns(cursor, parcel_schema, parcel_name)
        }
        has_geom = "geom" in lower_cols or "geometry" in lower_cols
        if not has_geom:
            errors.append(
                PreflightError(
                    field="parcel_table",
                    message=(
                        f"Table {parcel_schema}.{parcel_name} has no geometry "
                        "column (expected 'geom' or 'geometry')."
                    ),
                ),
            )

        # ── 3. Parcel table has an ID column ────────────────────────
        id_candidates = {"id", "gid", "fid", "objectid", "ogc_fid", "parcel_id"}
        has_id = bool(lower_cols & id_candidates)
        if not has_id:
            errors.append(
                PreflightError(
                    field="parcel_table",
                    message=(
                        f"Table {parcel_schema}.{parcel_name} has no recognized "
                        "ID column (expected one of: id, gid, fid, objectid, "
                        "ogc_fid, parcel_id)."
                    ),
                ),
            )

        # ── 4. Built forms table exists and has rows ───────────────
        if built_form_table:
            bt_schema, bt_name = _split(schema, built_form_table)
            bt_exists = _table_exists(cursor, bt_schema, bt_name)
            if not bt_exists:
                errors.append(
                    PreflightError(
                        field="built_form_table",
                        message=(
                            f"Built form table {bt_schema}.{bt_name} not "
                            "found. Run 'Export Building Types' first."
                        ),
                    ),
                )
            else:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {_qi(bt_schema, bt_name)}",
                )
                (bt_count,) = cursor.fetchone()
                if bt_count == 0:
                    errors.append(
                        PreflightError(
                            field="built_form_table",
                            message=(
                                f"Built form table {bt_schema}.{bt_name} "
                                "is empty. Run 'Export Building Types' first."
                            ),
                        ),
                    )

        # ── 5. Base canvas table exists ────────────────────────────
        if base_canvas_table:
            bc_schema, bc_name = _split(schema, base_canvas_table)
            if not _table_exists(cursor, bc_schema, bc_name):
                errors.append(
                    PreflightError(
                        field="base_canvas_table",
                        message=(
                            f"Base canvas table {bc_schema}.{bc_name} "
                            "not found. Import a base map first or use the "
                            "auto-generated staging stub."
                        ),
                    ),
                )

    return errors


def _split(schema: str, table: str) -> tuple[str, str]:
    """Split a possibly schema-qualified table reference.

    Falls back to *schema* when *table* has no schema prefix, matching the
    qualification convention used elsewhere (e.g.
    ``analysis.pipeline._build_model_vars``).
    """
    if "." in table:
        table_schema, table_name = table.split(".", 1)
        return table_schema, table_name
    return schema, table


def _table_exists(cursor: Any, schema: str, table: str) -> bool:
    """Check if a table exists in the given schema."""
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
        """,
        [schema, table],
    )
    (exists,) = cursor.fetchone()
    return bool(exists)


def _get_columns(cursor: Any, schema: str, table: str) -> list[str]:
    """Return column names for a table."""
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        [schema, table],
    )
    return [row[0] for row in cursor.fetchall()]


def _qi(schema: str, table: str) -> str:
    """Return a double-quoted PostgreSQL identifier."""
    return f'"{schema}"."{table}"'
