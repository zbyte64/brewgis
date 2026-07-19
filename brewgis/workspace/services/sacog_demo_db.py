"""Shared logic for restoring the SACOG demo database from .sql.gz dump.

This module provides a standalone :func:`restore_sacog_demo_db` function
that can be called from management commands, or any other
code path that needs the SACOG v1 reference tables available.
"""

from __future__ import annotations

import gzip
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

DEMO_DB_FILE = (
    Path(settings.BASE_DIR) / "planning" / "urbanfootprint-sacog-source-db.sql.gz"
)

MISSING_SCHEMAS = [
    "urbanfootprint_reference_datasets",
    "sacog_scenarios",
]

MISSING_ROLES = [
    "postgres",
]
OWNER_PATTERN = "OWNER TO calthorpe"

# COPY statements targeting extension-owned tables must be stripped
# to avoid duplicate key violations (spatial_ref_sys is managed by PostGIS).
SKIP_COPY_TABLES = {"spatial_ref_sys"}


class RestoreError(Exception):
    """Raised when the SACOG demo database restore fails."""


def _check_prerequisites() -> None:
    """Verify file exists and psql is available."""
    if not DEMO_DB_FILE.exists():
        msg = (
            f"Demo database file not found at {DEMO_DB_FILE}\n"
            "Expected file: planning/urbanfootprint-sacog-source-db.sql.gz"
        )
        raise RestoreError(msg)

    if not DEMO_DB_FILE.is_file():
        msg = f"Path exists but is not a file: {DEMO_DB_FILE}"
        raise RestoreError(msg)

    try:
        subprocess.run(
            ["psql", "--version"],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        msg = "psql not found. Install postgresql-client or rebuild the Docker image."
        raise RestoreError(msg) from None


def _clean_existing_objects(log: Any = None) -> None:
    """Drop existing objects from previous restores.

    Drops all non-extension tables and functions in public schema,
    plus the custom schemas used by the dump.
    """
    write = getattr(log, "write", None) or logger.info

    write("Cleaning existing objects from previous restores...")
    with connection.cursor() as cursor:
        cursor.execute("""
            DO $$ DECLARE
                r RECORD;
            BEGIN
                FOR r IN (
                    SELECT t.tablename
                    FROM pg_tables t
                    WHERE t.schemaname = 'public'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_depend d
                        WHERE d.refclassid = 'pg_extension'::regclass
                        AND d.classid = 'pg_class'::regclass
                        AND d.objid = (t.tablename)::regclass
                        AND d.deptype = 'e'
                    )
                ) LOOP
                    EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
                END LOOP;
            END $$;
        """)
        write("  \u2713 Dropped existing non-extension tables in public schema")

        cursor.execute("""
            DO $$ DECLARE
                r RECORD;
            BEGIN
                FOR r IN (
                    SELECT p.proname,
                           pg_get_function_identity_arguments(p.oid) AS args
                    FROM pg_proc p
                    WHERE p.pronamespace = 'public'::regnamespace
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_depend d
                        WHERE d.refclassid = 'pg_extension'::regclass
                        AND d.classid = 'pg_proc'::regclass
                        AND d.objid = p.oid
                        AND d.deptype = 'e'
                    )
                ) LOOP
                    EXECUTE 'DROP FUNCTION IF EXISTS public.' || quote_ident(r.proname)
                            || '(' || COALESCE(r.args, '') || ') CASCADE';
                END LOOP;
            END $$;
        """)
        write("  \u2713 Dropped existing non-extension functions in public schema")

        for schema in MISSING_SCHEMAS:
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        write(f"  \u2713 Dropped schemas if they existed: {', '.join(MISSING_SCHEMAS)}")


def _create_missing_schemas(log: Any = None) -> None:
    """Create schemas and roles referenced by the dump."""
    write = getattr(log, "write", None) or logger.info

    write("Creating missing schemas...")
    with connection.cursor() as cursor:
        for schema in MISSING_SCHEMAS:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            write(f"  \u2713 Schema '{schema}' created or already exists")

    write("Creating missing roles...")
    with connection.cursor() as cursor:
        for role in MISSING_ROLES:
            cursor.execute(
                f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
            write(f"  \u2713 Role '{role}' created or already exists")


def _get_database_url() -> str:
    """Get database URL from environment (set by Docker Compose)."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_conf = settings.DATABASES["default"]
        db_url = (
            f"postgresql://{db_conf['USER']}:{db_conf['PASSWORD']}"
            f"@{db_conf['HOST']}:{db_conf['PORT'] or 5432}/{db_conf['NAME']}"
        )
    return db_url


def _restore(sql_file: Path, db_url: str, log: Any = None) -> None:
    """Stream the .sql.gz through preprocessing into psql."""
    write = getattr(log, "write", None) or logger.info

    compressed_size = sql_file.stat().st_size
    write(f"Starting restore ({compressed_size / (1024 * 1024):.0f}MB compressed)...")
    write("This may take several minutes for the 1.6GB dump.")

    psql = subprocess.Popen(
        ["psql", "--set", "ON_ERROR_STOP=1", db_url],
        stdin=subprocess.PIPE,
        text=True,
    )

    lines_stripped = 0
    copy_lines_skipped = 0
    in_skip_copy = False
    try:
        with gzip.open(str(sql_file), "rt", errors="replace") as f:
            for line in f:
                if in_skip_copy:
                    if line.strip() == r"\.":
                        in_skip_copy = False
                    continue

                if line.startswith("COPY "):
                    table_part = line.split()[1]
                    table_name = table_part.rsplit(".", 1)[-1]
                    if table_name in SKIP_COPY_TABLES:
                        if line.strip().endswith("FROM stdin;"):
                            in_skip_copy = True
                            continue
                        copy_lines_skipped += 1
                        continue

                if OWNER_PATTERN in line:
                    lines_stripped += 1
                    continue
                if psql.stdin:
                    psql.stdin.write(line)
    except (OSError, EOFError) as e:
        if psql.stdin:
            psql.stdin.close()
        psql.wait()
        msg = f"Error reading dump file: {e}"
        raise RestoreError(msg) from e

    if psql.stdin:
        psql.stdin.close()
    psql.wait()

    if lines_stripped:
        write(f"Stripped {lines_stripped} OWNER TO calthorpe lines")

    if copy_lines_skipped:
        write(f"Skipped {copy_lines_skipped} COPY lines for extension-owned tables")

    if psql.returncode != 0:
        msg = (
            f"psql exited with code {psql.returncode}. "
            "Check the error output above for details."
        )
        raise RestoreError(msg)


def _fix_elk_grove_land_use_srid(log: Any = None) -> None:
    """Fix SRID 900914 → 2226 on public.elk_grove_land_use.

    The SACOG v1 dump assigns SRID 900914 (a non-standard custom code) to
    ``public.elk_grove_land_use.wkb_geometry``.  The actual projection is
    NAD83 / California zone 2 (US survey feet) — EPSG:2226.  Since
    ``spatial_ref_sys`` is managed by the PostGIS extension and the dump's
    ``spatial_ref_sys`` COPY is intentionally skipped during restore,
    SRID 900914 has no definition, causing downstream tools (tipg, Martin)
    to fail when they discover the geometry column.

    This function is a no-op if the table doesn't exist or already has a
    different SRID (already fixed).
    """
    write = getattr(log, "write", None) or logger.info

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM geometry_columns
            WHERE f_table_schema = 'public'
              AND f_table_name = 'elk_grove_land_use'
              AND f_geometry_column = 'wkb_geometry'
              AND srid = 900914
            """
        )
        if not cursor.fetchone():
            return

        cursor.execute(
            "SELECT UpdateGeometrySRID('public', 'elk_grove_land_use', 'wkb_geometry', 2226)"
        )
        cursor.execute(
            """
            SELECT 1 FROM geometry_columns
            WHERE f_table_schema = 'public'
              AND f_table_name = 'elk_grove_land_use'
              AND f_geometry_column = 'wkb_geometry'
              AND srid = 2226
            """
        )
        if cursor.fetchone():
            write("  \u2713 Fixed public.elk_grove_land_use SRID: 900914 \u2192 2226")
        else:
            write("  \u26a0 Failed to fix public.elk_grove_land_use SRID")


def restore_sacog_demo_db(log: Any = None) -> None:
    """Restore the SACOG demo database from the compressed SQL dump.

    This is the main entry point for auto-loading SACOG v1 reference tables.
    It checks prerequisites, cleans existing objects, creates required
    schemas and roles, then pipes the compressed SQL dump through psql.

    Args:
        log: Optional output stream (e.g. ``self.stdout`` from a management
            command). Defaults to ``logging.info``.

    Raises:
        RestoreError: If any step of the restore process fails.
    """
    write = getattr(log, "write", None) or logger.info

    sql_file = DEMO_DB_FILE
    file_size_mb = sql_file.stat().st_size / (1024 * 1024)
    write(f"Restoring demo database from {sql_file} ({file_size_mb:.0f}MB compressed)")

    _check_prerequisites()
    _clean_existing_objects(log=log)
    _create_missing_schemas(log=log)

    db_url = _get_database_url()
    _restore(sql_file, db_url, log=log)

    # Fix geometry SRID on SACOG land-use table imported from the v1 dump.
    # The dump assigns SRID 900914 (a non-standard code) to
    # public.elk_grove_land_use.wkb_geometry, which is actually
    # NAD83 / California zone 2 (US survey feet) = EPSG:2226.
    # SRID 900914 is not registered in PostGIS spatial_ref_sys, causing
    # tile-server startups (tipg) to crash with
    # "Cannot find SRID (900914) in spatial_ref_sys".
    _fix_elk_grove_land_use_srid(log=log)

    write("Demo database restored successfully")
