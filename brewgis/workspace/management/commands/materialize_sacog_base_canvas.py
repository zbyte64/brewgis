"""Management command — materialize a SACOG v1 table as an adoptable base canvas.

Turns a v1-shaped source table (``sac_cnty_region_base_canvas`` by default) into
a table carrying every ``BaseCanvasSchema`` column, so a workspace can adopt the
*imported* SACOG layer as its base canvas the same way it adopts a SQLMesh
model's view — see ``services.sqlmesh_tables.list_base_canvas_candidates``.

Why a table and not the v1 view: the picker offers loaded tables, and a
materialized table gives the canvas a column set and typmods identical to the
contract (``parcel_id BIGINT PRIMARY KEY``, ``geometry GEOMETRY(MultiPolygon,
4326)``, painted columns numeric). The projection is
``services.sacog_column_mapping.build_materialized_select_sql``; this command
owns the DDL, the load, and the post-load verification.

Usage:
    make sacog-base-canvas
    python manage.py materialize_sacog_base_canvas
    python manage.py materialize_sacog_base_canvas --source-table public.elk_grove_base_canvas \
        --target-table public.elk_grove_base_canvas_v3 --replace

Rebuilding an existing target truncates and reloads it, which keeps the views
that read it (every scenario canvas of a workspace on that table) valid.
``--replace`` drops it first instead, which PostgreSQL cascades to those views:
run ``python manage.py reconcile_scenario_canvases`` afterwards, or re-select
the base canvas on each workspace.
"""

# ruff: noqa: S608  # every interpolated identifier comes from _parts() or BaseCanvasSchema

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import connection

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.sacog_column_mapping import ALL_MAPPINGS
from brewgis.workspace.services.sacog_column_mapping import (
    build_materialized_select_sql,
)
from brewgis.workspace.services.sqlmesh_tables import BaseCanvasCandidate
from brewgis.workspace.services.sqlmesh_tables import list_base_canvas_candidates

#: The region's v1 base canvas: what ``compare_sacog_basemap`` and
#: ``services.comparison_helpers`` call ``V1_BASE_CANVAS``, and what the SACOG
#: v1 reference numbers in the docs refer to (502,874 parcels). Not the mapping
#: module's ``V1_BASE_TABLE`` — that one defaults the demo *view* to Elk Grove.
DEFAULT_SOURCE_TABLE = "public.sac_cnty_region_base_canvas"
DEFAULT_TARGET_TABLE = "public.sacog_parcels_base_canvas"

#: v1 columns the projection reads, i.e. what makes a source a v1 base canvas.
REQUIRED_SOURCE_COLUMNS: tuple[str, ...] = tuple(
    sorted({m.v1_column for m in ALL_MAPPINGS if m.v1_column})
)

#: How many missing column names a failure message lists before eliding.
_SAMPLE_SIZE = 8


def _parts(qualified: str) -> tuple[str, str]:
    """Split a ``schema.table`` reference, refusing anything else."""
    schema, separator, table = qualified.partition(".")
    if not (separator and schema.isidentifier() and table.isidentifier()):
        msg = f"Expected a schema-qualified table name, got {qualified!r}"
        raise CommandError(msg)
    return schema, table


class Command(BaseCommand):
    """Load a SACOG v1 source table into a typed base canvas table."""

    help = (
        "Materialize a SACOG v1-shaped source table as an adoptable base canvas table"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Register command-line arguments."""
        parser.add_argument(
            "--source-table",
            type=str,
            default=DEFAULT_SOURCE_TABLE,
            help=(
                "v1-shaped source table to read parcels from "
                f"(schema.table, default {DEFAULT_SOURCE_TABLE})"
            ),
        )
        parser.add_argument(
            "--target-table",
            type=str,
            default=DEFAULT_TARGET_TABLE,
            help=f"base canvas table to write (schema.table, default {DEFAULT_TARGET_TABLE})",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            default=False,
            help="Drop the target first, cascading to the views that read it",
        )

    def handle(self, **options: object) -> None:
        """Materialize the source into the target and verify the result."""
        source = str(options["source_table"])
        target = str(options["target_table"])
        # Validate both names before anything reaches the database, and quote
        # them once: every statement below interpolates these references.
        source_schema, source_name = _parts(source)
        target_schema, target_name = _parts(target)
        source_ref = f'"{source_schema}"."{source_name}"'
        target_ref = f'"{target_schema}"."{target_name}"'
        if source_ref == target_ref:
            msg = "--source-table and --target-table must differ"
            raise CommandError(msg)

        self.stdout.write(f"[1/6] Checking source {source}")
        source_columns = self._source_columns(source, source_schema, source_name)
        self._check_source_columns(source, source_columns)
        rows = self._scalar(f"SELECT count(*) FROM {source_ref}")
        self.stdout.write(f"  {rows:,} parcels, {len(source_columns)} columns")

        self.stdout.write(f"[2/6] Creating {target}")
        self._create_target(target_ref, replace=bool(options["replace"]))

        self.stdout.write("[3/6] Loading parcels")
        self._load(source_ref, target_ref)
        loaded = self._scalar(f"SELECT count(*) FROM {target_ref}")
        if loaded != rows:
            msg = f"{target} holds {loaded:,} rows after loading {rows:,} from {source}"
            raise CommandError(msg)
        self.stdout.write(f"  {loaded:,} rows")

        self.stdout.write("[4/6] Indexing")
        for statement in BaseCanvasSchema.create_indexes_sql(
            target_ref, index_basename=f"idx_{target_name}"
        ):
            self._execute(statement)
        self._execute(f"ANALYZE {target_ref}")

        self.stdout.write("[5/6] Verifying")
        self._verify(
            source_ref,
            target_ref,
            source_columns=len(source_columns),
            target_name=target_name,
            target_schema=target_schema,
        )

        self.stdout.write("[6/6] Reporting")
        pop, hh, du, emp = self._fetched(
            f"SELECT coalesce(sum(pop), 0), coalesce(sum(hh), 0), "
            f"coalesce(sum(du), 0), coalesce(sum(emp), 0) FROM {target_ref}"
        )
        self.stdout.write(f"  pop={pop:,.0f} hh={hh:,.0f} du={du:,.0f} emp={emp:,.0f}")
        self.stdout.write(
            self.style.SUCCESS(
                f"  {target} is adoptable: workspace → Select Base Canvas… → Imported tables"
            )
        )

    # ── Steps ─────────────────────────────────────────────────────────

    def _source_columns(self, source: str, schema: str, table: str) -> dict[str, str]:
        """Return ``{column: udt_name}`` for *source*, or raise if it is absent."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                [schema, table],
            )
            columns = dict(cursor.fetchall())
        if not columns:
            msg = f"Source table not found: {source}"
            raise CommandError(msg)
        return columns

    def _check_source_columns(self, source: str, columns: dict[str, str]) -> None:
        """Raise unless the source carries every column the projection reads."""
        missing = [name for name in REQUIRED_SOURCE_COLUMNS if name not in columns]
        if missing:
            listed = ", ".join(missing[:_SAMPLE_SIZE])
            more = ", …" if len(missing) > _SAMPLE_SIZE else ""
            msg = (
                f"{source} is not a SACOG v1 base canvas source: "
                f"{len(missing)} of {len(REQUIRED_SOURCE_COLUMNS)} mapped columns are missing "
                f"({listed}{more})"
            )
            raise CommandError(msg)
        if columns.get("wkb_geometry") not in {"geometry", "geography"}:
            msg = (
                f"{source}.wkb_geometry is {columns.get('wkb_geometry')!r}, "
                f"expected a geometry column"
            )
            raise CommandError(msg)

    def _create_target(self, target: str, *, replace: bool) -> None:
        """Create *target* with the base canvas DDL, dropping it first if asked."""
        if replace:
            self._execute(f"DROP TABLE IF EXISTS {target} CASCADE")
            self.stdout.write("  dropped the existing table and the views over it")
        self._execute(BaseCanvasSchema.create_table_sql(target))

    def _load(self, source: str, target: str) -> None:
        """Truncate *target* and insert the projected source rows."""
        self._execute(f"TRUNCATE {target}")
        columns = ", ".join(f'"{name}"' for name in BaseCanvasSchema.COLUMN_NAMES)
        projection = build_materialized_select_sql(source)
        self._execute(f"INSERT INTO {target} ({columns})\n{projection}")

    def _verify(
        self,
        source: str,
        target: str,
        *,
        source_columns: int,
        target_name: str,
        target_schema: str,
    ) -> None:
        """Raise unless the loaded table honors the contract and the projection.

        *source* and *target* are quoted references; *target_schema*/*target_name*
        are their parts, for the catalog lookup.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                [target_schema, target_name],
            )
            row = cursor.fetchone()
        actual = int(row[0]) if row else 0
        expected = len(BaseCanvasSchema.COLUMN_NAMES)
        if actual != expected:
            msg = f"{target} has {actual} columns, expected {expected}"
            raise CommandError(msg)

        with connection.cursor() as cursor:
            cursor.execute(f"SELECT DISTINCT ST_SRID(geometry) FROM {target}")
            srids = sorted({int(row[0]) for row in cursor.fetchall()})
        if srids != [BaseCanvasSchema.GEOMETRY_SRID]:
            msg = (
                f"{target}.geometry has SRIDs {srids}, "
                f"expected [{BaseCanvasSchema.GEOMETRY_SRID}]"
            )
            raise CommandError(msg)

        # Every column, not a sample of them: the loaded table must equal the
        # projection itself. That is what catches a truncated VARCHAR(n) cast, a
        # column the INSERT listed in the wrong order, and a mapping reading the
        # wrong source column.
        columns = [f'"{name}"' for name in BaseCanvasSchema.COLUMN_NAMES]
        loaded = ", ".join(f"t.{name}" for name in columns)
        projected = ", ".join(f"p.{name}" for name in columns)
        self._execute(
            f"CREATE OR REPLACE TEMP VIEW materialized_check AS "
            f"{build_materialized_select_sql(source)}"
        )
        try:
            mismatched = self._scalar(
                f"SELECT count(*) FROM materialized_check p "
                f"FULL JOIN {target} t USING (parcel_id) "
                f"WHERE ({loaded}) IS DISTINCT FROM ({projected})"
            )
            if mismatched:
                # Only now, to name the columns instead of just counting rows.
                differences = self._differing_columns(target, loaded, projected)
                listed = ", ".join(
                    f"{name} ({count:,})" for name, count in differences[:_SAMPLE_SIZE]
                )
                msg = (
                    f"{mismatched:,} rows in {target} disagree with the projection of "
                    f"{source}: {listed}"
                )
                raise CommandError(msg)
        finally:
            self._execute("DROP VIEW IF EXISTS materialized_check")

        qualified = f"{target_schema}.{target_name}"
        candidates: list[BaseCanvasCandidate] = list_base_canvas_candidates()
        if not any(
            candidate.qualified == qualified and not candidate.is_sqlmesh_model
            for candidate in candidates
        ):
            msg = f"{target} does not satisfy the base canvas contract; the picker will not offer it"
            raise CommandError(msg)
        self.stdout.write(
            f"  {source_columns} source columns → {actual} base canvas columns, "
            f"SRID {BaseCanvasSchema.GEOMETRY_SRID}, every value matches the projection"
        )
        self.stdout.write("  offered by the base canvas picker as an imported table")

    def _differing_columns(
        self, target: str, loaded: str, projected: str
    ) -> list[tuple[str, int]]:
        """Return ``[(column, rows)]`` for each column that disagrees, worst first."""
        differing: list[tuple[str, int]] = []
        loaded_row = f"({loaded})"
        projected_row = f"({projected})"
        for name in BaseCanvasSchema.COLUMN_NAMES:
            quoted = f'"{name}"'
            count = self._scalar(
                f"SELECT count(*) FROM materialized_check p "
                f"FULL JOIN {target} t USING (parcel_id) "
                f"WHERE {loaded_row} IS DISTINCT FROM {projected_row} "
                f"AND t.{quoted} IS DISTINCT FROM p.{quoted}"
            )
            if count:
                differing.append((name, count))
        return sorted(differing, key=lambda item: item[1], reverse=True)

    # ── SQL helpers ───────────────────────────────────────────────────

    def _execute(self, sql: str) -> None:
        """Run a statement."""
        with connection.cursor() as cursor:
            cursor.execute(sql)

    def _fetched(self, sql: str) -> tuple:
        """Run a query and return its first row."""
        with connection.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
        return row if row is not None else ()

    def _scalar(self, sql: str) -> int:
        """Run a query and return its single value as an int."""
        (value,) = self._fetched(sql)
        return int(value)
