"""Compare brewgis base canvas vs SACOG v1 reference — per-column report with aggregate + correlation stats.

The pipeline now uses SQLMesh models for the ETL and comparison stages,
with Soda validation checkpoints to catch data quality issues early.

This management command is kept for backward compatibility.

"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from sqlmesh import Context

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services._db import text
from brewgis.workspace.services.sacog_demo_db import restore_sacog_demo_db

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
_TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT_PATH = CACHE_DIR / f"sacog_comparison_report_{_TIMESTAMP}.md"
LOG_FILE_PATH = CACHE_DIR / f"sacog_comparison_{_TIMESTAMP}.log"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
logger = logging.getLogger(__name__)
STATE_FIPS = "06"
COUNTY_FIPS = "067"
SACOG_COUNTIES = ["067", "005", "017", "061"]  # Sacramento, Amador, El Dorado, Placer
# Vintage data years matching the SACOG v1 reference (2008-2012 era)
ACS_YEAR = 2013  # ACS 5-year 2009-2013 (earliest with block group API support)
LEHD_YEAR = 2008  # LODES 2008 (employment stats)
NLCD_YEAR = 2011  # NLCD 2011 (closest to 2008-2012)

LOCAL_SRID = 3310


def _repair_missing_indexes(
    context: Context, environment: str, model_fqns: list[str]
) -> int:
    """Scan each model's post_statements for CREATE INDEX, check pg_indexes,
    and create any indexes missing on the physical table.

    Uses the SQLMesh context to read the live model definition (no hardcoded
    index lists).  Resolves ``@this_model`` to the physical table name via the
    latest snapshot's ``table_name()`` — the same version the plan will backfill.
    """
    import re

    engine = get_engine()
    repaired = 0

    for fqn in model_fqns:
        model = context.get_model(fqn)
        if model is None:
            continue
        raw_statements = getattr(model, "post_statements", [])
        if not raw_statements:
            continue

        snapshot = context.get_snapshot(fqn, raise_if_missing=False)
        if snapshot is None or not snapshot.version:
            logger.debug("No snapshot for %s — skipping", fqn)
            continue
        physical_table = snapshot.table_name()
        # Verify the physical table exists — the snapshot can exist in state
        # (from a previous plan) without the table having been created yet.
        schema, table = physical_table.split(".", 1)[-1].rsplit(".", 1)
        with engine.connect() as conn:
            table_exists = conn.execute(
                text(
                    "SELECT 1 FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname = :schema AND c.relname = :table"
                ),
                {"schema": schema, "table": table},
            ).fetchone()
        if not table_exists:
            logger.debug("Physical table %s not yet created — skipping", physical_table)
            continue
        for stmt in raw_statements:
            # Convert SQLGlot expression to SQL text
            sql_text = stmt.sql(dialect="postgres")
            # Strip /* post_statements */ comment prefix if present
            sql_text = re.sub(r"^/\*[^*]*\*/\s*", "", sql_text).strip()
            if not sql_text.upper().startswith("CREATE INDEX"):
                continue

            # Resolve @this_model → physical table
            rendered = sql_text.replace("@this_model", physical_table)
            # Resolve @snapshot_hash → hash digits from physical table name
            # (e.g. "sqlmesh__assessor.assessor__sacog_assessor_parcels__962285576" → "962285576")
            hash_suffix = physical_table.rsplit("__", 1)[-1]
            rendered = rendered.replace("@snapshot_hash", hash_suffix)
            m = re.search(r"IF\s+NOT\s+EXISTS\s+(\S+)", rendered)
            if not m:
                continue
            idx_name = m.group(1).strip('"')

            # Scope to the specific physical table — the index name alone
            # can match an older snapshot version that has it.
            # snapshot.table_name() may return 3-part (catalog.schema.table)
            # or 2-part (schema.table); pg_indexes uses 2-part only.
            table_2part = physical_table.split(".", 1)[-1]
            schema, table = table_2part.rsplit(".", 1)
            with engine.begin() as conn:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM pg_indexes"
                        " WHERE indexname = :idx"
                        "   AND schemaname = :schema"
                        "   AND tablename = :table"
                    ),
                    {"idx": idx_name, "schema": schema, "table": table},
                ).fetchone()
                if row is None:
                    logger.warning(
                        "Missing index %s on %s (%s) — creating",
                        idx_name,
                        fqn,
                        physical_table,
                    )
                    conn.execute(text(rendered))
                    repaired += 1

    if repaired:
        logger.info("Repaired %d missing index(es)", repaired)
    return repaired


class _TeeOutput:
    """Write to both a console stdout and a log file.

    All writes go to the console (styled) and the log file (unstyled).
    Compatible with Django's ``OutputWrapper`` interface used by
    ``BaseCommand.stdout``.
    """

    def __init__(self, console, log_file) -> None:
        self._console = console
        self._log_file = log_file

    def write(self, msg, style_func=None, ending=None) -> None:
        ending = (
            ending if ending is not None else getattr(self._console, "_ending", "\n")
        )
        # Forward unstyled to log file first
        self._log_file.write(msg)
        if ending:
            self._log_file.write(ending)
        self._log_file.flush()
        # Forward styled to console
        self._console.write(msg, style_func=style_func, ending=ending)

    def flush(self) -> None:
        self._console.flush()
        self._log_file.flush()

    def __getattr__(self, name):
        return getattr(self._console, name)


class Command(BaseCommand):
    help = (
        "Create a brewgis base canvas for the SACOG/Sacramento region using the "
        "same parcel geometries as the v1 reference, then produce a comparison report."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--nlcd",
            action="store_true",
            default=True,
            help="Enable NLCD land cover classification and irrigation estimation",
        )
        parser.add_argument(
            "--osm",
            action="store_true",
            default=False,
            help="Enable OSM intersection density estimation",
        )
        parser.add_argument(
            "--overture-roads",
            action="store_true",
            default=True,
            help="Enable Overture Transportation road impervious diagnostics",
        )
        parser.add_argument(
            "--force-data-fetch",
            action="store_true",
            default=False,
            help="Ignore cached data and re-download",
        )

        parser.add_argument(
            "--force-data-reload",
            action="store_true",
            default=False,
            help="Clear and reload data into database from cached downloads (does not re-download from upstream sources)",
        )

        parser.add_argument(
            "--quick-parcel-clipping",
            action="store_true",
            default=False,
            help="Use faster ST_ClipByBox2D instead of accurate ST_Intersection for parcel-block area allocation (default: off, uses ST_Intersection)",
        )

        parser.add_argument(
            "--use-assessor-geometry",
            action="store_true",
            default=True,
            help="Use Sacramento County Assessor parcel geometries + building data for dasymetric weight refinement",
        )

        parser.add_argument(
            "--log-file",
            type=str,
            default="",
            help="Path to log file (default: planning/sacog_comparison_<timestamp>.log)",
        )
        parser.add_argument(
            "--no-log-file",
            action="store_true",
            default=False,
            help="Disable file logging (default: off, file logging enabled)",
        )
        parser.add_argument(
            "--report-path",
            type=str,
            default="",
            help="Path for the comparison report (default: planning/sacog_comparison_report_<timestamp>.md)",
        )
        parser.add_argument(
            "--environment",
            type=str,
            default="prod",
            help="sqlmesh evnrionment",
        )
        parser.add_argument(
            "--restate-model",
            action="extend",
            default=[],
            dest="restate_models",
            nargs="+",
            help="Model FQN(s) to restate during the checkpoint phase. Can be specified multiple times.",
        )

    def handle(self, **options: Any) -> None:
        # ── Resolve output paths ─────────────────────────────────────
        report_path_str = str(options.get("report_path", ""))
        if report_path_str:
            report_path = Path(report_path_str)
        else:
            import brewgis.workspace.management.commands.compare_sacog_basemap as _cmd_mod

            report_path = _cmd_mod.REPORT_PATH  # timestamped default

        # ── Setup file logging (tee to log file) ────────────────────
        no_log_file = bool(options.get("no_log_file", False))
        log_file_handle: object | None = None
        original_stdout = self.stdout
        log_path: Path | None = None

        if not no_log_file:
            log_path_str = str(options.get("log_file", ""))
            if log_path_str:
                log_path = Path(log_path_str)
            else:
                log_path = LOG_FILE_PATH  # timestamped default

            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file_handle = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            self.stdout = _TeeOutput(self.stdout, log_file_handle)

            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(levelname)s %(asctime)s %(module)s %(message)s")
            )
            # Add to both the module logger (for our messages)
            # and the root logger (for SQLMesh and other loggers).
            logger.addHandler(file_handler)
            logging.getLogger().addHandler(file_handler)
            # Prevent double-write when module logger propagates to root.
            logger.propagate = False
            self.stdout.write(f"Log file: {log_path}")

        self.stdout.write(f"Report: {report_path}")

        nlcd = bool(options.get("nlcd", False))
        osm = bool(options.get("osm", False))
        overture_roads = bool(options.get("overture_roads", False))
        force_data_fetch = bool(options.get("force_data_fetch", False))
        force_data_reload = bool(options.get("force_data_reload", False))
        quick_parcel_clipping = bool(options.get("quick_parcel_clipping", False))
        use_assessor_geometry = bool(options.get("use_assessor_geometry", False))
        environment = options.get("environment", "prod")
        restate_models: list[str] = options.get("restate_models", [])

        # TODO check if base_canvas exists / migrations are up to date

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  SACOG Base Canvas Comparison: BrewGIS vs v1 Reference")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  NLCD: {'on' if nlcd else 'off'}")
        self.stdout.write(f"  OSM: {'on' if osm else 'off'}")
        self.stdout.write(f"  Overture Roads: {'on' if overture_roads else 'off'}")
        self.stdout.write(
            f"  Assessor parcel geometry + dasymetric: {'on' if use_assessor_geometry else 'off'}"
        )
        self.stdout.write(
            f"  Force re-download: {'yes' if force_data_fetch else 'no (use cached data if available)'}"
        )
        self.stdout.write(
            f"  Force data reload: {'yes' if force_data_reload else 'no (use cached data if available)'}"
        )
        self.stdout.write(
            f"  Parcel clipping: {'fast (ClipByBox2D)' if quick_parcel_clipping else 'accurate (Intersection)'}"
        )
        if not settings.CENSUS_API_KEY:
            raise CommandError(
                "  WARNING: CENSUS_API_KEY is not set. Census ACS and CBP API calls will fail. "
                "Set CENSUS_API_KEY in your .env file. Get a free key at "
                "https://api.census.gov/data/key_signup.html"
            )

        # ── Pre-flight: Ensure SACOG v1 reference tables are loaded ────

        try:
            self._run(
                nlcd=nlcd,
                osm=osm,
                overture_roads=overture_roads,
                force_data_fetch=force_data_fetch,
                force_data_reload=force_data_reload,
                quick_parcel_clipping=quick_parcel_clipping,
                use_assessor_geometry=use_assessor_geometry,
                log_file_handle=log_file_handle,
                report_path=report_path,
                environment=environment,
                restate_models=restate_models,
            )
        except Exception:
            logger.exception("compare_sacog_basemap failed")
            self.stderr.write(
                self.style.ERROR(
                    "\nCommand failed — check log file for full traceback."
                )
            )
            raise
        finally:
            if log_file_handle is not None:
                log_file_handle.close()
            self.stdout = original_stdout

    # ─────────────────────────────────────────────────────────────────────────────
    # Pipeline runner
    # ─────────────────────────────────────────────────────────────────────────────

    def _run(
        self,
        *,
        nlcd: bool,
        osm: bool,
        overture_roads: bool,
        force_data_fetch: bool,
        force_data_reload: bool,
        quick_parcel_clipping: bool,
        use_assessor_geometry: bool,
        log_file_handle: Any,
        report_path: Path,
        environment: str,
        restate_models: list[str] | None = None,
    ) -> None:
        # Lazy imports — avoid loading analysis modules at import time
        # which conflicts with test stubs for pandas/geopandas.
        from brewgis.workspace.analysis.sqlmesh_runner import get_context
        from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline
        from brewgis.workspace.services.census_fetcher import _populate_acs_block_group
        from brewgis.workspace.services.comparison_helpers import (
            _convert_reference_totals,
        )
        from brewgis.workspace.services.comparison_helpers import (
            _generate_report_markdown,
        )
        from brewgis.workspace.services.comparison_helpers import _load_parcels
        from brewgis.workspace.services.comparison_helpers import _query_table_as_dict
        from brewgis.workspace.services.lehd_fetcher import _populate_wac_block

        self.stdout.write("\n── Pre-flight: Checking SACOG reference tables ──")
        if not self._table_has_rows("public", V1_PARCELS):
            self.stdout.write(
                "  SACOG reference tables not found. Auto-restoring demo database..."
            )
            restore_sacog_demo_db(log=self.stdout)
            self.stdout.write(
                self.style.SUCCESS("  SACOG reference tables restored successfully")
            )
        else:
            self.stdout.write(
                "  SACOG reference tables already present, skipping restore"
            )
        # ── Override SQLMesh config variables to match SACOG comparison years ──

        # ── Phase 1: Load parcels into SQLMesh source table ────────────────
        self.stdout.write("\n── Phase 1: Loading reference parcel geometries ──")

        parcel_checksum = self._parcel_checksum(
            get_engine(), "sacog_comparison_parcels"
        )
        source_checksum = self._parcel_checksum(get_engine(), V1_PARCELS)

        if (
            force_data_fetch
            or parcel_checksum is None
            or parcel_checksum != source_checksum
        ):
            parcels_gdf = _load_parcels(0)
            self.stdout.write(f"  Loaded {len(parcels_gdf):,} parcels")

            # Normalize SACOG column names to SQLMesh contract
            # SACOG source uses geography_id; SQLMesh models expect parcel_id and id.
            parcels_gdf["parcel_id"] = parcels_gdf["geography_id"]
            parcels_gdf["id"] = parcels_gdf["geography_id"]
            self.stdout.write(
                f"  Normalized {len(parcels_gdf):,} rows: geography_id → parcel_id, id"
            )

            # Drop with CASCADE — SQLMesh views may depend on this table
            with get_engine().begin() as conn:
                conn.execute(
                    text("DROP TABLE IF EXISTS public.sacog_comparison_parcels CASCADE")
                )

            # Write to SQLMesh source table (sacog_comparison_parcels)
            parcels_gdf.to_postgis(
                "sacog_comparison_parcels",
                get_engine(),
                schema="public",
                if_exists="replace",
                index=False,
                dtype={"geometry": f"geometry(MultiPolygon, {LOCAL_SRID})"},
            )
            self.stdout.write("  Written to public.sacog_comparison_parcels")
            # Btree indexes for JOINs in sacog_parcel_shim.sql, parcels_wm.sql, parcel_block_groups, etc.
            with get_engine().begin() as conn:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_sacog_comparison_parcels_parcel_id "
                        "ON public.sacog_comparison_parcels (parcel_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_sacog_comparison_parcels_geography_id "
                        "ON public.sacog_comparison_parcels (geography_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_sacog_comparison_parcels_geometry "
                        "ON public.sacog_comparison_parcels USING GIST (geometry)"
                    )
                )
        else:
            self.stdout.write("  Parcels already loaded and unchanged, skipping")

        # ── Conditional data loading ──────────────────────────────────

        # Populate TIGER/Line block group polygons (needed by ACS reader)
        self.stdout.write("\n── TIGER/Line block group staging (DuckDB zipfs) ──")
        self.stdout.write("  TIGER/Line BG: data served from DuckDB zipfs staging VIEW")

        # Populate TIGER/Line block polygons (needed by wac_block_raw)
        self.stdout.write("\n── TIGER/Line block staging (DuckDB zipfs) ──")
        self.stdout.write(
            "  TIGER/Line blocks: data served from DuckDB zipfs staging VIEW"
        )

        # Populate Census ACS staging table
        self.stdout.write("\n── Census ACS staging (DuckDB httpfs VIEW) ──")
        self.stdout.write("  Census ACS: data served from DuckDB httpfs staging VIEW")

        # Populate census.acs_block_group from ACS staging + TIGER BG geometry
        self.stdout.write("\n── Populating census.acs_block_group ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("staging__brewgis_prod", "acs_block_group")
        ):
            acs_bg_count = _populate_acs_block_group(
                STATE_FIPS, SACOG_COUNTIES, ACS_YEAR
            )
            self.stdout.write(
                f"  census.acs_block_group populated: {acs_bg_count:,} rows"
            )
        else:
            self.stdout.write("  census.acs_block_group already populated, skipping")

        # Populate Census 2020 block staging table
        self.stdout.write("\n── Census 2020 block staging (DuckDB httpfs VIEW) ──")
        self.stdout.write(
            "  Census 2020 blocks: data served from DuckDB httpfs staging VIEW"
        )

        # Populate Census PDB staging table
        self.stdout.write("\n── Census PDB staging (DuckDB httpfs VIEW) ──")
        self.stdout.write("  Census PDB: data served from DuckDB httpfs staging VIEW")

        # Populate LEHD staging table before ETL
        self.stdout.write("\n── LEHD LODES staging (DuckDB httpfs VIEW) ──")
        self.stdout.write("  LEHD LODES: data served from DuckDB httpfs staging VIEW")

        # Populate lehd.wac_block from LEHD staging + TIGER geometry
        self.stdout.write("\n── Populating lehd.wac_block ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("staging__brewgis_prod", "wac_block")
        ):
            lehd_wac_count = _populate_wac_block(
                STATE_FIPS, COUNTY_FIPS, year=LEHD_YEAR
            )
            self.stdout.write(f"  lehd.wac_block populated: {lehd_wac_count:,} rows")
        else:
            self.stdout.write("  lehd.wac_block already populated, skipping")
        # ── Phase 1.5: Optional data pipelines (conditional) ─────────

        if use_assessor_geometry:
            # Assessor parcels and sales now served from DuckDB GeoParquet staging.
            # Download from ArcGIS REST services and write parquet files so
            # duckdb.staging.assessor_parcels and duckdb.staging.assessor_sales
            # (SQLMesh VIEWs) can read them. The bridge FULL models then copy
            # into the brewgis.staging schema for PostGIS access.
            from brewgis.workspace.services.assessor_fetcher import fetch_parcels_arcgis
            from brewgis.workspace.services.assessor_fetcher import fetch_sales_arcgis
            from brewgis.workspace.services.assessor_fetcher import write_to_geoparquet

            assessor_parquet_dir = Path(settings.BASE_DIR) / "planning" / "assessor"
            assessor_parquet_dir.mkdir(parents=True, exist_ok=True)
            parcels_parquet = assessor_parquet_dir / "assessor_parcels.parquet"
            sales_parquet = assessor_parquet_dir / "assessor_sales.parquet"

            self.stdout.write("\n── Populating Assessor parcel geometries ──")
            if force_data_fetch or force_data_reload or not parcels_parquet.exists():
                self.stdout.write("  Downloading assessor parcels from ArcGIS...")
                parcels_gdf = fetch_parcels_arcgis()
                result = write_to_geoparquet(parcels=parcels_gdf)
                self.stdout.write(
                    f"  Downloaded {result.get('parcels', 0):,} parcels → {parcels_parquet}"
                )
            else:
                self.stdout.write("  Assessor parcels already cached, skipping")

            self.stdout.write("\n── Populating Assessor building characteristics ──")
            if force_data_fetch or force_data_reload or not sales_parquet.exists():
                self.stdout.write("  Downloading assessor sales data from ArcGIS...")
                sales_gdf = fetch_sales_arcgis()
                result = write_to_geoparquet(sales=sales_gdf)
                self.stdout.write(
                    f"  Downloaded {result.get('sales', 0):,} sales records → {sales_parquet}"
                )
            else:
                self.stdout.write("  Assessor sales already cached, skipping")

        if osm:
            self.stdout.write("\n── Computing OSM intersection density ──")
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "osm_intersection_density")
            ):
                osm_result = run_osm_pipeline(
                    parcel_table="sacog_comparison_parcels",  # why is this different? investigate swapping
                )
                self.stdout.write(
                    f"  OSM intersection density loaded: {osm_result.get('row_count', 0)} rows"
                )
            else:
                self.stdout.write("  OSM intersection density already loaded, skipping")

        # ── Phase 2: Single consolidated SQLMesh plan call ─────────────────
        self.stdout.write("\n── Phase 2: Running consolidated SQLMesh plan ──")

        model_selectors: list[str] = [
            "+brewgis.staging.acs_bridge",
            "+brewgis.comparison.sacog_parcel_shim",
            "+brewgis.staging.census_2020_block",
            "+brewgis.base_canvas.base_canvas_reconciled",
            "+brewgis.comparison.sacog_summary",
        ]
        if False and nlcd:
            model_selectors.extend(
                [
                    "+brewgis.nlcd.parcels_wm",
                    "+brewgis.nlcd.nlcd_parcel_stats",
                    "+brewgis.nlcd.nlcd_tree_canopy_parcel_stats",
                ]
            )
        if False and use_assessor_geometry:
            model_selectors.extend(
                [
                    "+brewgis.staging.overture_buildings",
                    "+brewgis.staging.vida_combined_buildings",
                    "+brewgis.assessor.sacog_assessor_parcels",
                    "+brewgis.assessor.sacog_assessor_sales",
                    "+brewgis.assessor.assessor_building_medians",
                    "+brewgis.assessor.buildings_combined",
                    "+brewgis.assessor.parcel_building_footprints",
                    "+brewgis.assessor.parcel_block_groups",
                    "+brewgis.assessor.parcel_footprint_imputed",
                    "+brewgis.assessor.authoritative_residential_area",
                    "+brewgis.assessor.parcel_dasymetric_weights",
                    "+brewgis.comparison.training_parcel_map",
                    "+brewgis.comparison.sacog_dasymetric",
                ]
            )
        if False and overture_roads:
            model_selectors.extend(
                [
                    "+brewgis.staging.overture_transport",
                    "+brewgis.nlcd.overture_road_impervious",
                ]
            )

        plan_vars: dict[str, object] = {
            "parcel_table": "brewgis.comparison.sacog_parcel_shim",
            "local_srid": LOCAL_SRID,
            "acs_year": ACS_YEAR,
            "state_fips": STATE_FIPS,
            "county_fips": ",".join(SACOG_COUNTIES),
            # CBP county-level employment controls for 2008 (Sacramento County, CA)
            "cbp_county_emp_agriculture": 195,
            "cbp_county_emp_extraction": 168,
            "cbp_county_emp_construction": 34731,
            "cbp_county_emp_manufacturing": 23768,
            "cbp_county_emp_transport_warehousing": 10494,
            "cbp_county_emp_utilities": 1894,
            "cbp_county_emp_wholesale": 21107,
            "cbp_county_emp_retail_services": 63192,
            "cbp_county_emp_office_services": 103310,
            "cbp_county_emp_education": 8385,
            "cbp_county_emp_medical_services": 70577,
            "cbp_county_emp_arts_entertainment": 7794,
            "cbp_county_emp_accommodation": 4267,
            "cbp_county_emp_restaurant": 42351,
            "cbp_county_emp_other_services": 61210,
            "cbp_county_emp_public_admin": 0,  # not available in CBP for 2008
            "cbp_preserve_fraction": 0.5,
        }
        if osm:
            plan_vars["osm_intersection_table"] = "osm_intersection_density"

        # --- environment invalidation ---
        restate_models_list: list[str] = [
            *(restate_models or []),
        ]
        selector_fqns = [s.lstrip("+") for s in model_selectors]

        if force_data_reload:
            if environment == "prod":
                if restate_models:
                    restate_models_list.extend(
                        [
                            *selector_fqns,
                            "brewgis.base_canvas.base_canvas_geometry",
                            "brewgis.base_canvas.base_canvas_combined",
                            "brewgis.base_canvas.base_canvas_imputed",
                        ]
                    )
            else:
                reload_context = get_context(**plan_vars)
                reload_context.invalidate_environment(environment)
                logger.info("Invalidated sacog_comparison environment for full rebuild")

        plan, context = run_sqlmesh_plan(
            environment=environment,
            skip_tests=False,
            select=model_selectors,
            variables=plan_vars,
            restate_models=restate_models_list or False,
        )
        self.stdout.write(self.style.SUCCESS("  SQLMesh models complete"))

        # ── Phase 4: Read results from SQLMesh-materialized tables ─────────
        self.stdout.write("\n── Phase 4: Reading comparison data from SQLMesh ──")
        sacog_summary_table = context.table_name(
            "brewgis.comparison.sacog_summary",
            environment,
        )
        summary = _query_table_as_dict(sacog_summary_table)
        # fetchdf assumes prod environment
        # summary = context.fetchdf("SELECT * from brewgis.comparison.sacog_summary limit 1").iloc[0].to_dict()

        # Split summary columns by prefix
        ref_totals = {k[4:]: v for k, v in summary.items() if k.startswith("ref_")}
        brew_totals = {k[5:]: v for k, v in summary.items() if k.startswith("brew_")}
        correlations = {k[5:]: v for k, v in summary.items() if k.startswith("corr_")}
        weighted_means = {k: v for k, v in summary.items() if k.endswith("_wavg")}

        _convert_reference_totals(ref_totals)

        if ref_totals:
            self._print_totals(ref_totals, "Reference v1")
        if brew_totals:
            self._print_totals(brew_totals, "BrewGIS")

        # ── Phase 5: Generate comparison report ────────────────────────
        self.stdout.write("\n── Phase 5: Generating comparison report ──")
        dasymetric_table = context.table_name(
            "brewgis.comparison.sacog_dasymetric", environment
        )
        reconciled_table = context.table_name(
            "brewgis.base_canvas.base_canvas_reconciled", environment
        )
        authoritative_table = (
            context.table_name(
                "brewgis.assessor.authoritative_residential_area",
                environment,
            )
            if use_assessor_geometry
            else None
        )
        assessor_parcels_table = (
            context.table_name(
                "brewgis.assessor.sacog_assessor_parcels",
                environment,
            )
            if use_assessor_geometry
            else None
        )
        building_footprints_table = (
            context.table_name(
                "brewgis.assessor.parcel_building_footprints",
                environment,
            )
            if use_assessor_geometry
            else None
        )
        resnet_features_table = context.table_name(
            "brewgis.assessor.parcel_resnet_features",
            environment,
        )
        overture_transport_table = context.table_name(
            "brewgis.staging.overture_transport",
            environment,
        )
        overture_road_impervious_table = context.table_name(
            "brewgis.nlcd.overture_road_impervious",
            environment,
        )
        _generate_report_markdown(
            ref_totals,
            brew_totals,
            correlations=correlations,
            weighted_means=weighted_means,
            config={
                "nlcd": nlcd,
                "osm": osm,
                "overture-roads": overture_roads,
                "use-assessor-geometry": use_assessor_geometry,
                "quick-parcel-clipping": quick_parcel_clipping,
                "lehd-year": LEHD_YEAR,
                "acs-year": ACS_YEAR,
                "nlcd-year": NLCD_YEAR,
            },
            diagnostics=_collect_diagnostics(
                engine=get_engine(),
                dasymetric_table=dasymetric_table if use_assessor_geometry else None,
                authoritative_table=authoritative_table,
                assessor_parcels_table=assessor_parcels_table,
                building_footprints_table=building_footprints_table,
                reconciled_table=reconciled_table,
                resnet_features_table=resnet_features_table,
                overture_transport_table=overture_transport_table
                if overture_roads
                else None,
                overture_road_impervious_table=overture_road_impervious_table
                if overture_roads
                else None,
                overture_roads=overture_roads,
            ),
            output_path=report_path,
            quick=not (nlcd or osm),
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Report written to {report_path}"))
        self.stdout.write(self.style.SUCCESS(f"  Done — open {report_path} to review"))

    # ═══════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _table_has_rows(schema: str, table: str) -> bool:
        """Check if a table exists and has at least one row."""
        engine = get_engine()
        with engine.connect() as conn:
            count = conn.execute(
                text(
                    f"SELECT EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_schema = '{schema}' AND table_name = '{table}')"
                )
            ).scalar()
            if count == 0:
                return False
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {schema}.{table}")  # noqa: S608 — schema/table are hardcoded literals
            ).scalar()
            return bool(count) and count > 0

    @staticmethod
    def _parcel_checksum(engine: Any, table: str) -> str | None:
        """Return an MD5 checksum of parcel geography_ids, or None if table doesn't exist."""
        with engine.connect() as conn:
            exists = conn.execute(
                text(
                    f"SELECT EXISTS ( SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{table}')"
                )
            ).scalar()
            if not exists:
                return None
            row = conn.execute(
                text(
                    f"SELECT MD5(string_agg(geography_id::text, ',' ORDER BY geography_id)) FROM public.{table}"
                )
            ).scalar()
            return row

    def _print_totals(self, totals: dict[str, float], label: str) -> None:
        """Print key aggregate totals."""
        col_map = {
            "acres_gross": ("area_gross_acres", "acres_gross"),
            "acres_parcel": ("area_parcel_acres", "acres_parcel"),
            "pop": ("pop", "pop"),
            "hh": ("hh", "hh"),
            "du": ("du", "du"),
            "emp": ("emp", "emp"),
        }

        self.stdout.write(f"  *** {label} ***")
        for label_name, (v3_col, v1_col) in col_map.items():
            val = totals.get(v3_col) or totals.get(v1_col)
            if val is not None:
                self.stdout.write(f"    {label_name:25s} {val:>14,.0f}")

    def _generate_report(
        self,
        ref: dict[str, float],
        brew: dict[str, float],
        etl_result: dict,
        quick: bool,
        correlations: dict[str, float] | None = None,
        weighted_means: dict[str, float] | None = None,
    ):
        """Generate the markdown comparison report (thin wrapper for backward compat).

        Legacy method expected by test suite. Delegates to
        ``_generate_report_markdown``.
        """
        # Lazy imports — avoid loading analysis modules at import time
        import brewgis.workspace.management.commands.compare_sacog_basemap as _cmd_mod
        from brewgis.workspace.services.comparison_helpers import (
            _generate_report_markdown,
        )

        report_path = _cmd_mod.REPORT_PATH

        _generate_report_markdown(
            ref,
            brew,
            correlations=correlations or {},
            weighted_means=weighted_means or {},
            output_path=report_path,
            quick=quick,
        )


def _collect_diagnostics(
    engine: Engine,
    dasymetric_table: str | None = None,
    authoritative_table: str | None = None,
    assessor_parcels_table: str | None = None,
    building_footprints_table: str | None = None,
    reconciled_table: str | None = None,
    resnet_features_table: str | None = None,
    overture_transport_table: str | None = None,
    overture_road_impervious_table: str | None = None,
    overture_roads: bool = False,
) -> dict:
    """Collect calibration diagnostics from materialized SQLMesh tables.

    Queries the database for assessor coverage, DU sub-type breakdown,
    authoritative building intersection diagnostics, employment pipeline
    statistics, and ResNet feature coverage.

    Args:
        engine: SQLAlchemy database engine.
        dasymetric_table: Dasymetric weights table name, or None if not used.
        authoritative_table: Authoritative residential area table name, or None
            to skip building intersection diagnostics.
        reconciled_table: Materialized base_canvas_reconciled table name,
            or None to skip land-development-category diagnostics.
        resnet_features_table: ResNet feature snapshot table name, or None
            to skip ResNet coverage diagnostics.

    Returns:
        Dict with keys ``dasymetric``, ``assessor``, ``employment``,
        ``resnet`` containing diagnostic metrics.
    """
    from brewgis.workspace.services._db import text

    diagnostics: dict = {
        "dasymetric": {
            "total_parcels": 0,
            "assessor_parcels": 0,
            "pop_weight_parcels": 0,
        },
        "assessor": {},
        "employment": {"total_wac_blocks": 0, "wac_blocks_with_geom": 0},
    }

    if dasymetric_table:
        with engine.connect() as conn:
            # Total parcels
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {dasymetric_table}")
            ).scalar()
            diagnostics["dasymetric"]["total_parcels"] = row or 0

            # Parcels with du_subtype
            row = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {dasymetric_table} WHERE du_subtype IS NOT NULL"
                )
            ).scalar()
            diagnostics["dasymetric"]["assessor_parcels"] = row or 0

            # Parcels with pop_dasym_weight
            row = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {dasymetric_table} WHERE pop_dasym_weight IS NOT NULL"
                )
            ).scalar()
            diagnostics["dasymetric"]["pop_weight_parcels"] = row or 0

            # DU sub-type breakdown
            subtype_rows = conn.execute(
                text(f"""
                    SELECT COALESCE(du_subtype, 'NULL') AS st, COUNT(*) AS cnt
                    FROM {dasymetric_table}
                    GROUP BY du_subtype
                    ORDER BY cnt DESC
                """)
            ).fetchall()
            diagnostics["dasymetric"]["du_subtype_breakdown"] = {
                row[0]: row[1] for row in subtype_rows
            }

            # Land development category from base_canvas_reconciled
            if reconciled_table:
                try:
                    lc_rows = conn.execute(
                        text(f"""
                            SELECT COALESCE(land_development_category, 'NULL') AS cat, COUNT(*) AS cnt
                            FROM {reconciled_table}
                            GROUP BY land_development_category
                            ORDER BY cnt DESC
                        """)
                    ).fetchall()
                    diagnostics["assessor"]["land_development_category"] = {
                        row[0]: row[1] for row in lc_rows
                    }
                except Exception:
                    pass

    # Employment pipeline: WAC block counts
    with engine.connect() as conn:
        try:
            row = conn.execute(
                text("SELECT COUNT(*) FROM staging__brewgis_prod.wac_block")
            ).scalar()
            diagnostics["employment"]["total_wac_blocks"] = row or 0
        except Exception:
            pass
        try:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM staging__brewgis_prod.wac_block WHERE geometry IS NOT NULL"
                )
            ).scalar()
            diagnostics["employment"]["wac_blocks_with_geom"] = row or 0
        except Exception:
            pass

    # ResNet feature coverage
    diagnostics["resnet"] = {
        "total_rows": 0,
        "unique_parcels": 0,
        "comparison_parcels_with_features": 0,
        "comparison_parcels_total": 0,
        "min_lon": 0.0,
        "min_lat": 0.0,
        "max_lon": 0.0,
        "max_lat": 0.0,
    }
    if resnet_features_table and dasymetric_table:
        with engine.connect() as conn:
            try:
                row = conn.execute(
                    text(f"SELECT COUNT(*) FROM {resnet_features_table}")
                ).scalar()
                diagnostics["resnet"]["total_rows"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(DISTINCT parcel_id) FROM {resnet_features_table}"
                    )
                ).scalar()
                diagnostics["resnet"]["unique_parcels"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM ("
                        f"  SELECT d.parcel_id FROM {dasymetric_table} d "
                        f"  WHERE EXISTS ("
                        f"    SELECT 1 FROM {resnet_features_table} rf "
                        f"    WHERE rf.parcel_id::text = d.parcel_id::text"
                        f"  )"
                        f") sub"
                    )
                ).scalar()
                diagnostics["resnet"]["comparison_parcels_with_features"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(f"SELECT COUNT(*) FROM {dasymetric_table}")
                ).scalar()
                diagnostics["resnet"]["comparison_parcels_total"] = row or 0
            except Exception:
                pass
            # Spatial extent of ResNet parcels
            try:
                row = conn.execute(
                    text(
                        f"SELECT "
                        f"  ROUND(MIN(ST_XMin(d.geometry))::numeric, 4), "
                        f"  ROUND(MIN(ST_YMin(d.geometry))::numeric, 4), "
                        f"  ROUND(MAX(ST_XMax(d.geometry))::numeric, 4), "
                        f"  ROUND(MAX(ST_YMax(d.geometry))::numeric, 4) "
                        f"FROM {dasymetric_table} d "
                        f"WHERE EXISTS ("
                        f"  SELECT 1 FROM {resnet_features_table} rf "
                        f"  WHERE rf.parcel_id::text = d.parcel_id::text"
                        f")"
                    )
                ).fetchone()
                if row:
                    (
                        diagnostics["resnet"]["min_lon"],
                        diagnostics["resnet"]["min_lat"],
                        diagnostics["resnet"]["max_lon"],
                        diagnostics["resnet"]["max_lat"],
                    ) = (float(v) if v is not None else 0.0 for v in row)
            except Exception:
                pass

    # Authoritative Building Intersection Diagnostics
    diagnostics["authoritative"] = {
        "overture_residential_match": 0,
        "assessor_sales_only": 0,
        "footprint_imputed": 0,
        "no_authoritative_data": 0,
        "total_parcels": 0,
        "mean_acres_overture": 0.0,
        "mean_acres_assessor_only": 0.0,
        "mean_acres_footprint_imputed": 0.0,
        "mean_acres_no_data": 0.0,
        "median_acres_overture": 0.0,
        "median_acres_assessor_only": 0.0,
        "median_acres_footprint_imputed": 0.0,
        "median_acres_no_data": 0.0,
        "building_count_breakdown": {},
        "straddling_buildings": 0,
        "parcels_with_straddling": 0,
        "coverage_by_category": {},
    }
    if authoritative_table:
        with engine.connect() as conn:
            # Total parcels with authoritative data
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {authoritative_table}")
            ).scalar()
            total = row or 0
            diagnostics["authoritative"]["total_parcels"] = total

            # Parcels with Overture residential buildings (data_source = overture_*)
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {authoritative_table}
                    WHERE data_source IN ('overture_with_levels', 'overture_flat')
                """)
            ).scalar()
            diagnostics["authoritative"]["overture_residential_match"] = row or 0

            # Parcels with assessor sales only (no Overture)
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {authoritative_table}
                    WHERE data_source = 'assessor_sales'
                """)
            ).scalar()
            diagnostics["authoritative"]["assessor_sales_only"] = row or 0

            # Parcels with footprint-imputed data
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {authoritative_table}
                    WHERE data_source = 'footprint_imputed'
                """)
            ).scalar()
            diagnostics["authoritative"]["footprint_imputed"] = row or 0

            # Parcels with no authoritative data
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM {authoritative_table}
                    WHERE data_source IS NULL
                """)
            ).scalar()
            diagnostics["authoritative"]["no_authoritative_data"] = row or 0

            # Parcel size stats per category
            try:
                rows = conn.execute(
                    text(f"""
                        SELECT
                            CASE
                                WHEN data_source IN ('overture_with_levels', 'overture_flat')
                                THEN 'overture'
                                ELSE COALESCE(data_source, 'none')
                            END AS cat,
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lot_size_acres) AS median_acres,
                            AVG(lot_size_acres) AS mean_acres
                        FROM (
                            SELECT a.*, sap.lot_size_acres
                            FROM {authoritative_table} a
                            LEFT JOIN {assessor_parcels_table or "brewgis.assessor.sacog_assessor_parcels"} sap
                                ON a.apn = sap.apn
                        ) sub
                        GROUP BY cat
                    """)
                ).fetchall()
                for row in rows:
                    cat = str(row[0])
                    if cat == "overture":
                        diagnostics["authoritative"]["median_acres_overture"] = float(
                            row[1] or 0.0
                        )
                        diagnostics["authoritative"]["mean_acres_overture"] = float(
                            row[2] or 0.0
                        )
                    elif cat == "assessor_sales":
                        diagnostics["authoritative"]["median_acres_assessor_only"] = (
                            float(row[1] or 0.0)
                        )
                        diagnostics["authoritative"]["mean_acres_assessor_only"] = (
                            float(row[2] or 0.0)
                        )
                    elif cat == "footprint_imputed":
                        diagnostics["authoritative"][
                            "median_acres_footprint_imputed"
                        ] = float(row[1] or 0.0)
                        diagnostics["authoritative"]["mean_acres_footprint_imputed"] = (
                            float(row[2] or 0.0)
                        )
                    elif cat == "none":
                        diagnostics["authoritative"]["median_acres_no_data"] = float(
                            row[1] or 0.0
                        )
                        diagnostics["authoritative"]["mean_acres_no_data"] = float(
                            row[2] or 0.0
                        )
            except Exception:
                pass

            # Building count distribution
            if building_footprints_table:
                try:
                    rows = conn.execute(
                        text(f"""
                            SELECT
                                CASE
                                    WHEN residential_building_count = 0 THEN '0'
                                    WHEN residential_building_count = 1 THEN '1'
                                    WHEN residential_building_count BETWEEN 2 AND 5 THEN '2-5'
                                    WHEN residential_building_count BETWEEN 6 AND 10 THEN '6-10'
                                    WHEN residential_building_count BETWEEN 11 AND 50 THEN '11-50'
                                    ELSE '50+'
                                END AS bucket,
                                COUNT(*) AS cnt
                            FROM {building_footprints_table}
                            GROUP BY bucket
                            ORDER BY MIN(residential_building_count)
                        """)
                    ).fetchall()
                    diagnostics["authoritative"]["building_count_breakdown"] = {
                        str(row[0]): row[1] for row in rows
                    }
                except Exception:
                    pass

            # Straddling buildings — same building footprint geometry on multiple APNs
            if building_footprints_table:
                try:
                    row = conn.execute(
                        text(f"""
                            SELECT COUNT(*) FROM (
                                SELECT geometry::text
                                FROM {building_footprints_table}
                                WHERE total_footprint_sqft > 0
                                GROUP BY geometry::text
                                HAVING COUNT(DISTINCT apn) > 1
                            ) sub
                        """)
                    ).scalar()
                    diagnostics["authoritative"]["straddling_buildings"] = row or 0
                except Exception:
                    pass

                try:
                    row = conn.execute(
                        text(f"""
                            SELECT COUNT(DISTINCT bf.apn) FROM (
                                SELECT geometry::text AS geom_key
                                FROM {building_footprints_table}
                                WHERE total_footprint_sqft > 0
                                GROUP BY geometry::text
                                HAVING COUNT(DISTINCT apn) > 1
                            ) sub
                            JOIN {building_footprints_table} bf
                                ON sub.geom_key = bf.geometry::text
                        """)
                    ).scalar()
                    diagnostics["authoritative"]["parcels_with_straddling"] = row or 0
                except Exception:
                    pass

            # Coverage by land development category
            try:
                rows = conn.execute(
                    text(f"""
                        SELECT
                            COALESCE(sap.land_development_category, 'unknown') AS cat,
                            COUNT(*) AS total,
                            SUM(CASE WHEN a.data_source IS NOT NULL THEN 1 ELSE 0 END) AS covered,
                            AVG(CASE WHEN a.authoritative_residential_sqft > 0
                                THEN a.authoritative_residential_sqft ELSE NULL END
                            ) AS mean_sqft
                        FROM (
                            SELECT a.*, sap.lot_size_acres
                            FROM {authoritative_table} a
                            LEFT JOIN brewgis.assessor.sacog_assessor_parcels sap
                                ON a.apn = sap.apn
                        ) a
                        LEFT JOIN (
                            SELECT apn, COALESCE(auc.category, 'unknown') AS land_development_category
                            FROM brewgis.assessor.sacog_assessor_parcels
                            LEFT JOIN brewgis.seeds.assessor_use_codes auc
                                ON LEFT(COALESCE(landuse::text, ''), 2) = auc.use_code::text
                        ) sap ON a.apn = sap.apn
                        GROUP BY sap.land_development_category
                        ORDER BY sap.land_development_category
                    """)
                ).fetchall()
                diagnostics["authoritative"]["coverage_by_category"] = {
                    str(row[0]): {
                        "total": row[1],
                        "covered": row[2],
                        "mean_sqft": float(row[3] or 0.0),
                    }
                    for row in rows
                }
            except Exception:
                pass

    # Road surface diagnostics from Overture Transportation
    diagnostics["road_surface"] = {
        "segment_count": 0,
        "paved_segments": 0,
        "unpaved_segments": 0,
        "parcels_with_roads": 0,
        "total_parcels": 0,
        "total_road_paved_area": 0.0,
        "total_road_unpaved_area": 0.0,
        "avg_road_impervious_fraction": 0.0,
        "surface_class_breakdown": {},
    }
    if overture_roads:
        transport = overture_transport_table
        road_impervious = overture_road_impervious_table

        if not transport or not road_impervious:
            diagnostics["road_surface"]["error"] = (
                "Table not resolved: overture_transport_table="
                f"{transport}, overture_road_impervious_table={road_impervious}"
            )

        with engine.connect() as conn:
            try:
                row = conn.execute(
                    text(f"SELECT COUNT(*) AS cnt FROM {transport}")
                ).scalar()
                diagnostics["road_surface"]["segment_count"] = row or 0
            except Exception as exc:
                diagnostics["road_surface"]["error_segment_count"] = str(exc)
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(*) AS cnt FROM {transport} "
                        "WHERE surface IN ('paved', 'asphalt', 'concrete') OR surface IS NULL"
                    )
                ).scalar()
                diagnostics["road_surface"]["paved_segments"] = row or 0
            except Exception as exc:
                diagnostics["road_surface"]["error_paved_segments"] = str(exc)
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(*) AS cnt FROM {transport} "
                        "WHERE surface IN ('unpaved', 'gravel', 'dirt', 'earth', 'ground')"
                    )
                ).scalar()
                diagnostics["road_surface"]["unpaved_segments"] = row or 0
            except Exception as exc:
                diagnostics["road_surface"]["error_unpaved_segments"] = str(exc)
            try:
                rows = conn.execute(
                    text(
                        f"SELECT COALESCE(surface, 'NULL') AS surface_class, COUNT(*) AS cnt "
                        f"FROM {transport} "
                        "GROUP BY surface ORDER BY cnt DESC"
                    )
                ).fetchall()
                diagnostics["road_surface"]["surface_class_breakdown"] = {
                    row[0]: row[1] for row in rows
                }
            except Exception as exc:
                diagnostics["road_surface"]["error_surface_class_breakdown"] = str(exc)
            try:
                row = conn.execute(
                    text(
                        f"SELECT COUNT(DISTINCT parcel_id) AS cnt "
                        f"FROM {road_impervious} "
                        "WHERE road_total_area > 0"
                    )
                ).scalar()
                diagnostics["road_surface"]["parcels_with_roads"] = row or 0
            except Exception as exc:
                diagnostics["road_surface"]["error_parcels_with_roads"] = str(exc)
            try:
                row = conn.execute(
                    text(f"SELECT COUNT(*) AS cnt FROM {road_impervious}")
                ).scalar()
                diagnostics["road_surface"]["total_parcels"] = row or 0
            except Exception as exc:
                diagnostics["road_surface"]["error_total_parcels"] = str(exc)
            try:
                row = conn.execute(
                    text(
                        f"SELECT SUM(road_paved_area) AS paved, SUM(road_unpaved_area) AS unpaved "
                        f"FROM {road_impervious}"
                    )
                ).fetchone()
                if row:
                    diagnostics["road_surface"]["total_road_paved_area"] = float(
                        row[0] or 0.0
                    )
                    diagnostics["road_surface"]["total_road_unpaved_area"] = float(
                        row[1] or 0.0
                    )
            except Exception as exc:
                diagnostics["road_surface"]["error_road_area"] = str(exc)
            try:
                row = conn.execute(
                    text(
                        f"SELECT AVG(road_impervious_fraction) AS avg_frac "
                        f"FROM {road_impervious} "
                        "WHERE road_total_area > 0"
                    )
                ).scalar()
                diagnostics["road_surface"]["avg_road_impervious_fraction"] = float(
                    row or 0.0
                )
            except Exception as exc:
                diagnostics["road_surface"]["error_avg_impervious"] = str(exc)

    return diagnostics
