import gzip
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import connection

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


class Command(BaseCommand):
    help = "Restore the UrbanFootprint SACOG demo database from .sql.gz dump"

    def handle(self, *args, **options):
        self._check_prerequisites()

        sql_file = DEMO_DB_FILE
        file_size_mb = sql_file.stat().st_size / (1024 * 1024)
        self.stdout.write(
            f"Restoring demo database from {sql_file} ({file_size_mb:.0f}MB compressed)"
        )

        # Step 1: Clean existing objects from previous partial restores
        self._clean_existing_objects()
        self._create_missing_schemas()

        # Step 2: Get database URL for psql
        db_url = self._get_database_url()

        # Step 3: Preprocess and pipe to psql
        self._restore(sql_file, db_url)

        self.stdout.write(self.style.SUCCESS("Demo database restored successfully"))

    def _check_prerequisites(self) -> None:
        """Verify file exists and psql is available."""
        if not DEMO_DB_FILE.exists():
            msg = (
                f"Demo database file not found at {DEMO_DB_FILE}\n"
                "Expected file: planning/urbanfootprint-sacog-source-db.sql.gz"
            )
            raise CommandError(msg)

        if not DEMO_DB_FILE.is_file():
            msg = f"Path exists but is not a file: {DEMO_DB_FILE}"
            raise CommandError(msg)

        # Verify psql is available (postgresql-client package)
        try:
            subprocess.run(
                ["psql", "--version"],
                capture_output=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            msg = (
                "psql not found. Install postgresql-client or rebuild the Docker image."
            )
            raise CommandError(msg) from None

    def _clean_existing_objects(self) -> None:
        """Drop existing objects from previous restores.

        Drops all non-extension tables and functions in public schema,
        plus the custom schemas used by the dump.
        """
        self.stdout.write("Cleaning existing objects from previous restores...")
        with connection.cursor() as cursor:
            # Drop all non-extension tables in public schema
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
            self.stdout.write(
                "  ✓ Dropped existing non-extension tables in public schema"
            )

            # Drop all non-extension functions in public schema
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
            self.stdout.write(
                "  ✓ Dropped existing non-extension functions in public schema"
            )

            # Drop custom schemas if they exist (will be recreated)
            for schema in MISSING_SCHEMAS:
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            self.stdout.write(
                f"  ✓ Dropped schemas if they existed: {', '.join(MISSING_SCHEMAS)}"
            )

    def _create_missing_schemas(self) -> None:
        """Create schemas and roles referenced by the dump."""
        self.stdout.write("Creating missing schemas...")
        with connection.cursor() as cursor:
            for schema in MISSING_SCHEMAS:
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                self.stdout.write(f"  ✓ Schema '{schema}' created or already exists")

        self.stdout.write("Creating missing roles...")
        with connection.cursor() as cursor:
            for role in MISSING_ROLES:
                cursor.execute(
                    f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                )
                self.stdout.write(f"  ✓ Role '{role}' created or already exists")

    def _get_database_url(self) -> str:
        """Get database URL from environment (set by Docker Compose)."""
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            # Fallback: reconstruct from Django settings
            db_conf = settings.DATABASES["default"]
            db_url = (
                f"postgresql://{db_conf['USER']}:{db_conf['PASSWORD']}"
                f"@{db_conf['HOST']}:{db_conf['PORT'] or 5432}/{db_conf['NAME']}"
            )
        return db_url

    def _restore(self, sql_file: Path, db_url: str) -> None:
        """Stream the .sql.gz through preprocessing into psql."""
        compressed_size = sql_file.stat().st_size
        self.stdout.write(
            f"Starting restore ({compressed_size / (1024 * 1024):.0f}MB compressed)..."
        )
        self.stdout.write("This may take several minutes for the 1.6GB dump.")
        self.stdout.flush()

        # Start psql — inherit stdout/stderr so output appears in real-time
        psql = subprocess.Popen(
            ["psql", "--set", "ON_ERROR_STOP=1", db_url],
            stdin=subprocess.PIPE,
            text=True,
        )

        # Stream gzipped SQL through the line filter
        lines_stripped = 0
        copy_lines_skipped = 0
        in_skip_copy = False
        try:
            with gzip.open(str(sql_file), "rt", errors="replace") as f:
                for line in f:
                    # Track whether we're inside a COPY block for a table we skip
                    if in_skip_copy:
                        if line.strip() == r"\.":
                            in_skip_copy = False
                        continue

                    # Check for COPY statements targeting extension-owned tables
                    if line.startswith("COPY "):
                        table_part = line.split()[1]  # e.g. "public.spatial_ref_sys"
                        table_name = table_part.rsplit(".", 1)[
                            -1
                        ]  # just "spatial_ref_sys"
                        if table_name in SKIP_COPY_TABLES:
                            if line.strip().endswith("FROM stdin;"):
                                in_skip_copy = True
                                continue
                            # No-data COPY (COPY ... FROM stdin; with no data)
                            copy_lines_skipped += 1
                            continue

                    if OWNER_PATTERN in line:
                        lines_stripped += 1
                        continue
                    psql.stdin.write(line)
        except (OSError, EOFError) as e:
            # Close stdin so psql can finish processing what it has
            psql.stdin.close()
            psql.wait()
            msg = f"Error reading dump file: {e}"
            raise CommandError(msg) from e

        psql.stdin.close()
        psql.wait()

        if lines_stripped:
            self.stdout.write(f"Stripped {lines_stripped} OWNER TO calthorpe lines")

        if copy_lines_skipped:
            self.stdout.write(
                f"Skipped {copy_lines_skipped} COPY lines for extension-owned tables"
            )

        if psql.returncode != 0:
            msg = (
                f"psql exited with code {psql.returncode}. "
                "Check the error output above for details."
            )
            raise CommandError(msg)
