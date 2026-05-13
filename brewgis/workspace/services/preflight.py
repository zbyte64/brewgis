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
        if not _table_exists(cursor, schema, parcel_table):
            errors.append(
                PreflightError(
                    field="parcel_table",
                    message=f"Table {schema}.{parcel_table} not found.",
                ),
            )
            return errors  # Cannot proceed without the parcel table

        # ── 2. Parcel table has geometry column ─────────────────────
        lower_cols = {c.lower() for c in _get_columns(cursor, schema, parcel_table)}
        has_geom = "geom" in lower_cols or "geometry" in lower_cols
        if not has_geom:
            errors.append(
                PreflightError(
                    field="parcel_table",
                    message=(
                        f"Table {schema}.{parcel_table} has no geometry column "
                        "(expected 'geom' or 'geometry')."
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
                        f"Table {schema}.{parcel_table} has no recognized ID "
                        "column (expected one of: id, gid, fid, objectid, "
                        "ogc_fid, parcel_id)."
                    ),
                ),
            )

        # ── 4. Built forms table exists and has rows ───────────────
        if built_form_table:
            bt_exists = _table_exists(cursor, schema, built_form_table)
            if not bt_exists:
                errors.append(
                    PreflightError(
                        field="built_form_table",
                        message=(
                            f"Built form table {schema}.{built_form_table} not "
                            "found. Run 'Export Building Types' first."
                        ),
                    ),
                )
            else:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {_qi(schema, built_form_table)}",
                )
                (bt_count,) = cursor.fetchone()
                if bt_count == 0:
                    errors.append(
                        PreflightError(
                            field="built_form_table",
                            message=(
                                f"Built form table {schema}.{built_form_table} "
                                "is empty. Run 'Export Building Types' first."
                            ),
                        ),
                    )

        # ── 5. Base canvas table exists ────────────────────────────
        if base_canvas_table:
            if not _table_exists(cursor, schema, base_canvas_table):
                errors.append(
                    PreflightError(
                        field="base_canvas_table",
                        message=(
                            f"Base canvas table {schema}.{base_canvas_table} "
                            "not found. Import a base map first or use the "
                            "auto-generated staging stub."
                        ),
                    ),
                )

    return errors


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
