"""Compare brewgis base canvas vs SACOG v1 reference — per-column report with aggregate + correlation stats.

The pipeline now uses SQLMesh models for the ETL and comparison stages,
with Soda validation checkpoints to catch data quality issues early.

This management command is kept for backward compatibility.

"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

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
            default=False,
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
            default=False,
            help="Enable Overture Transportation road impervious diagnostics",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit parcel count for fast test runs (0 = all)",
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
            default=False,
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
            logger.addHandler(file_handler)
            logging.getLogger().addHandler(file_handler)
            self.stdout.write(f"Log file: {log_path}")

        self.stdout.write(f"Report: {report_path}")

        nlcd = bool(options.get("nlcd", False))
        osm = bool(options.get("osm", False))
        overture_roads = bool(options.get("overture_roads", False))
        limit = int(options.get("limit", 0))
        force_data_fetch = bool(options.get("force_data_fetch", False))
        force_data_reload = bool(options.get("force_data_reload", False))
        quick_parcel_clipping = bool(options.get("quick_parcel_clipping", False))
        use_assessor_geometry = bool(options.get("use_assessor_geometry", False))

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
        self.stdout.write(f"  Parcel limit: {limit or 'all'}")
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
                limit=limit,
                force_data_fetch=force_data_fetch,
                force_data_reload=force_data_reload,
                quick_parcel_clipping=quick_parcel_clipping,
                use_assessor_geometry=use_assessor_geometry,
                log_file_handle=log_file_handle,
                report_path=report_path,
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
        limit: int,
        force_data_fetch: bool,
        force_data_reload: bool,
        quick_parcel_clipping: bool,
        use_assessor_geometry: bool,
        log_file_handle: Any,
        report_path: Path,
    ) -> None:
        # Lazy imports — avoid loading analysis modules at import time
        # which conflicts with test stubs for pandas/geopandas.
        from brewgis.workspace.analysis.sqlmesh_runner import run_sqlmesh_plan
        from brewgis.workspace.dlt_pipelines.assessor import (
            run_assessor_parcels_pipeline,
        )
        from brewgis.workspace.dlt_pipelines.assessor import run_assessor_sales_pipeline
        from brewgis.workspace.dlt_pipelines.census import run_census_pipeline
        from brewgis.workspace.dlt_pipelines.census_2020 import run_census_2020_pipeline
        from brewgis.workspace.dlt_pipelines.lehd import run_lehd_pipeline
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_pipeline
        from brewgis.workspace.dlt_pipelines.nlcd import run_nlcd_tree_canopy_pipeline
        from brewgis.workspace.dlt_pipelines.osm import run_osm_pipeline
        from brewgis.workspace.dlt_pipelines.pdb import run_pdb_pipeline
        from brewgis.workspace.dlt_pipelines.tiger_bg import run_tiger_bg_pipeline
        from brewgis.workspace.dlt_pipelines.tiger_block import run_tiger_block_pipeline
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
            parcels_gdf = _load_parcels(limit)
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
        self.stdout.write("\n── Populating TIGER/Line block group staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "tiger_block_groups")
        ):
            tiger_result = run_tiger_bg_pipeline(
                STATE_FIPS, vintages=["2013", "2023"], ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  TIGER/Line BG loaded: {tiger_result.get('row_count', 0)} rows "
                f"in {tiger_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  TIGER/Line BG already loaded, skipping")

        # Populate TIGER/Line block polygons (needed by wac_block_raw)
        self.stdout.write("\n── Populating TIGER/Line block staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "tiger_blocks")
        ):
            tiger_block_result = run_tiger_block_pipeline(
                STATE_FIPS, vintages=["2020"], ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  TIGER/Line blocks loaded: {tiger_block_result.get('row_count', 0)} rows "
                f"in {tiger_block_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  TIGER/Line blocks already loaded, skipping")

        # Populate Census ACS staging table
        self.stdout.write("\n── Populating Census ACS staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "acs_raw")
        ):
            census_result = run_census_pipeline(
                STATE_FIPS, SACOG_COUNTIES, ACS_YEAR, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  Census ACS loaded: {census_result.get('row_count', 0)} rows "
                f"in {census_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  Census ACS already loaded, skipping")

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
        self.stdout.write("\n── Populating Census 2020 block staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "census_2020_block_raw")
        ):
            census_2020_result = run_census_2020_pipeline(
                STATE_FIPS, SACOG_COUNTIES, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  Census 2020 blocks loaded: {census_2020_result.get('row_count', 0)} rows "
                f"in {census_2020_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  Census 2020 blocks already loaded, skipping")

        # Populate Census PDB staging table
        self.stdout.write("\n── Populating Census PDB staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "pdb_raw")
        ):
            pdb_result = run_pdb_pipeline(
                STATE_FIPS, COUNTY_FIPS, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  Census PDB loaded: {pdb_result.get('row_count', 0)} rows "
                f"in {pdb_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  Census PDB already loaded, skipping")

        # Populate LEHD staging table before ETL
        self.stdout.write("\n── Populating LEHD LODES staging table ──")
        if (
            force_data_fetch
            or force_data_reload
            or not self._table_has_rows("public", "lodes_raw")
        ):
            lehd_result = run_lehd_pipeline(
                STATE_FIPS, COUNTY_FIPS, LEHD_YEAR, ignore_cache=force_data_fetch
            )
            self.stdout.write(
                f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows "
                f"in {lehd_result.get('table_name', '?')}"
            )
        else:
            self.stdout.write("  LEHD LODES already loaded, skipping")

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
        if nlcd:
            self.stdout.write("\n── Phase 1.5a: Computing NLCD zonal stats ──")
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "nlcd_raster")
            ):
                nlcd_result = run_nlcd_pipeline(
                    parcel_source="sacog_comparison_parcels",
                    year=NLCD_YEAR,
                    ignore_cache=force_data_fetch,
                )
                nlcd_raster_table = nlcd_result.get("raster_table", "nlcd_raster")
                self.stdout.write(
                    f"  NLCD raster loaded: {nlcd_result.get('row_count', 0)} tiles "
                    f"in public.{nlcd_raster_table}"
                )
            else:
                self.stdout.write("  NLCD raster already loaded, skipping")

            self.stdout.write(
                "\n── Phase 1.5b: Computing NLCD tree canopy zonal stats ──"
            )
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "nlcd_tree_canopy_raster")
            ):
                nlcd_tc_result = run_nlcd_tree_canopy_pipeline(
                    parcel_source="sacog_comparison_parcels",
                    year=NLCD_YEAR,
                    ignore_cache=force_data_fetch,
                )
                nlcd_tc_raster_table = nlcd_tc_result.get(
                    "raster_table", "nlcd_tree_canopy_raster"
                )
                self.stdout.write(
                    f"  NLCD tree canopy raster loaded: "
                    f"{nlcd_tc_result.get('row_count', 0)} tiles "
                    f"in public.{nlcd_tc_raster_table}"
                )
            else:
                self.stdout.write("  NLCD tree canopy raster already loaded, skipping")

        if use_assessor_geometry:
            # APN uniqueness pre-check: verify sacog_assessor_parcels_raw has no
            # duplicate APNs before running assessor models through SQLMesh plan.
            if self._table_has_rows("public", "sacog_assessor_parcels_raw"):
                engine = get_engine()
                with engine.connect() as conn:
                    total = conn.execute(
                        text("SELECT COUNT(*) FROM public.sacog_assessor_parcels_raw")
                    ).scalar()
                    distinct = conn.execute(
                        text(
                            "SELECT COUNT(DISTINCT apn) FROM public.sacog_assessor_parcels_raw"
                        )
                    ).scalar()
                    if distinct is not None and total is not None and total > distinct:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  WARNING: sacog_assessor_parcels_raw has {total - distinct:,} duplicate APNs "
                                f"({total:,} total rows, {distinct:,} distinct APNs). "
                                "Dropping table and reloading"
                            )
                        )
                        conn.execute(
                            text("DROP TABLE public.sacog_assessor_parcels_raw CASCADE")
                        )
            self.stdout.write("\n── Populating Assessor parcel geometries ──")
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "sacog_assessor_parcels_raw")
            ):
                assessor_parcels_result = run_assessor_parcels_pipeline(
                    max_pages=0 if not limit else max(1, limit // 2000 + 1),
                    ignore_cache=force_data_fetch,
                )
                self.stdout.write(
                    f"  Assessor parcels loaded: {assessor_parcels_result.get('row_count', 0)} rows"
                )
            else:
                self.stdout.write("  Assessor parcels already loaded, skipping")

            self.stdout.write("\n── Populating Assessor building characteristics ──")
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "sacog_assessor_sales_raw")
            ):
                assessor_sales_result = run_assessor_sales_pipeline(
                    max_pages=0 if not limit else max(1, limit // 2000 + 1),
                    ignore_cache=force_data_fetch,
                )
                self.stdout.write(
                    f"  Assessor sales loaded: {assessor_sales_result.get('row_count', 0)} rows"
                )
            else:
                self.stdout.write("  Assessor sales already loaded, skipping")

        if osm:
            self.stdout.write("\n── Computing OSM intersection density ──")
            if (
                force_data_fetch
                or force_data_reload
                or not self._table_has_rows("public", "osm_intersection_density")
            ):
                osm_result = run_osm_pipeline(
                    parcel_table="sacog_comparison_parcels",
                )
                self.stdout.write(
                    f"  OSM intersection density loaded: {osm_result.get('row_count', 0)} rows"
                )
            else:
                self.stdout.write("  OSM intersection density already loaded, skipping")

        # ── Phase 2: Single consolidated SQLMesh plan call ─────────────────
        self.stdout.write("\n── Phase 2: Running consolidated SQLMesh plan ──")

        model_selectors: list[str] = [
            "+brewgis.comparison.sacog_parcel_shim",
            "+brewgis.staging.census_2020_block",
            "+brewgis.base_canvas.base_canvas_reconciled",
            "+brewgis.comparison.sacog_summary",
        ]
        if nlcd:
            model_selectors.extend(
                [
                    "+brewgis.nlcd.parcels_wm",
                    "+brewgis.nlcd.nlcd_parcel_stats",
                    "+brewgis.nlcd.nlcd_tree_canopy_parcel_stats",
                ]
            )
        if use_assessor_geometry:
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
                    "+brewgis.comparison.sacog_comparison_dasymetric",
                ]
            )
        if overture_roads:
            model_selectors.extend(
                [
                    "+brewgis.staging.overture_transport",
                    "+brewgis.nlcd.overture_road_impervious",
                ]
            )

        plan_vars: dict[str, object] = {
            "parcel_table": "brewgis.comparison.sacog_parcel_shim",
            "local_srid": LOCAL_SRID,
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

        # checkpoint
        run_sqlmesh_plan(
            environment="sacog_comparison",
            skip_tests=False,
            select=[
                "+brewgis.comparison.sacog_reference_totals",
                "+brewgis.comparison.sacog_parcel_shim",
                "+brewgis.staging.census_2020_block",
            ],
            variables=plan_vars,
            restate_models=force_data_reload,
        )

        plan, context = run_sqlmesh_plan(
            environment="sacog_comparison",
            skip_tests=False,
            select=model_selectors,
            variables=plan_vars,
            restate_models=force_data_reload,
        )
        self.stdout.write(self.style.SUCCESS("  SQLMesh models complete"))

        # ── Phase 4: Read results from SQLMesh-materialized tables ─────────
        self.stdout.write("\n── Phase 4: Reading comparison data from SQLMesh ──")
        sacog_summary_table = context.table_name(
            "brewgis.comparison.sacog_summary", "sacog_comparison"
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
        dasymetric_table = (
            "brewgis.comparison__sacog_comparison.sacog_comparison_dasymetric"
        )
        reconciled_table = context.table_name(
            "brewgis.base_canvas.base_canvas_reconciled", "sacog_comparison"
        )
        authoritative_table = (
            context.table_name(
                "brewgis.assessor.authoritative_residential_area",
                "sacog_comparison",
            )
            if use_assessor_geometry
            else None
        )
        assessor_parcels_table = (
            context.table_name(
                "brewgis.assessor.sacog_assessor_parcels",
                "sacog_comparison",
            )
            if use_assessor_geometry
            else None
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
                reconciled_table=reconciled_table,
                overture_roads=overture_roads,
            ),
            output_path=report_path,
            quick=not (nlcd or osm),
            limit=limit,
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
        limit: int,
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
            limit=limit,
        )


def _collect_diagnostics(
    engine: Engine,
    dasymetric_table: str | None = None,
    authoritative_table: str | None = None,
    assessor_parcels_table: str | None = None,
    reconciled_table: str | None = None,
    overture_roads: bool = False,
) -> dict:
    """Collect calibration diagnostics from materialized SQLMesh tables.

    Queries the database for assessor coverage, DU sub-type breakdown,
    authoritative building intersection diagnostics, and employment pipeline
    statistics.

    Args:
        engine: SQLAlchemy database engine.
        dasymetric_table: Dasymetric weights table name, or None if not used.
        authoritative_table: Authoritative residential area table name, or None
            to skip building intersection diagnostics.
        reconciled_table: Materialized base_canvas_reconciled table name,
            or None to skip land-development-category diagnostics.

    Returns:
        Dict with keys ``dasymetric``, ``assessor``, ``employment`` containing
        diagnostic metrics.
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
                        FROM {authoritative_table}
                        GROUP BY bucket
                        ORDER BY MIN(residential_building_count)
                    """)
                ).fetchall()
                diagnostics["authoritative"]["building_count_breakdown"] = {
                    str(row[0]): row[1] for row in rows
                }
            except Exception:
                pass

            # Straddling buildings — buildings intersecting multiple parcels
            try:
                row = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM (
                            SELECT bc.apn
                            FROM brewgis.staging.buildings_combined bc
                            JOIN brewgis.assessor.sacog_assessor_parcels sap
                                ON ST_Intersects(
                                    ST_SetSRID(bc.geometry, 4326),
                                    sap.geometry
                                )
                            GROUP BY bc.geometry::text
                            HAVING COUNT(DISTINCT sap.apn) > 1
                        ) sub
                    """)
                ).scalar()
                diagnostics["authoritative"]["straddling_buildings"] = row or 0
            except Exception:
                pass

            try:
                row = conn.execute(
                    text("""
                        SELECT COUNT(DISTINCT sap.apn) FROM (
                            SELECT bc.geometry::text AS geom_key
                            FROM brewgis.staging.buildings_combined bc
                            JOIN brewgis.assessor.sacog_assessor_parcels sap
                                ON ST_Intersects(
                                    ST_SetSRID(bc.geometry, 4326),
                                    sap.geometry
                                )
                            GROUP BY bc.geometry::text
                            HAVING COUNT(DISTINCT sap.apn) > 1
                        ) sub
                        JOIN brewgis.staging.buildings_combined bc
                            ON sub.geom_key = bc.geometry::text
                        JOIN brewgis.assessor.sacog_assessor_parcels sap
                            ON ST_Intersects(
                                ST_SetSRID(bc.geometry, 4326),
                                sap.geometry
                            )
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
        with engine.connect() as conn:
            try:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM brewgis.staging.overture_transport"
                    )
                ).scalar()
                diagnostics["road_surface"]["segment_count"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM brewgis.staging.overture_transport "
                        "WHERE surface IN ('paved', 'asphalt', 'concrete') OR surface IS NULL"
                    )
                ).scalar()
                diagnostics["road_surface"]["paved_segments"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM brewgis.staging.overture_transport "
                        "WHERE surface IN ('unpaved', 'gravel', 'dirt', 'earth', 'ground')"
                    )
                ).scalar()
                diagnostics["road_surface"]["unpaved_segments"] = row or 0
            except Exception:
                pass
            try:
                rows = conn.execute(
                    text(
                        "SELECT COALESCE(surface, 'NULL') AS surface_class, COUNT(*) AS cnt "
                        "FROM brewgis.staging.overture_transport "
                        "GROUP BY surface ORDER BY cnt DESC"
                    )
                ).fetchall()
                diagnostics["road_surface"]["surface_class_breakdown"] = {
                    row[0]: row[1] for row in rows
                }
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT COUNT(DISTINCT parcel_id) AS cnt "
                        "FROM brewgis.nlcd.overture_road_impervious "
                        "WHERE road_total_area > 0"
                    )
                ).scalar()
                diagnostics["road_surface"]["parcels_with_roads"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM brewgis.nlcd.overture_road_impervious"
                    )
                ).scalar()
                diagnostics["road_surface"]["total_parcels"] = row or 0
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT SUM(road_paved_area) AS paved, SUM(road_unpaved_area) AS unpaved "
                        "FROM brewgis.nlcd.overture_road_impervious"
                    )
                ).fetchone()
                if row:
                    diagnostics["road_surface"]["total_road_paved_area"] = float(
                        row[0] or 0.0
                    )
                    diagnostics["road_surface"]["total_road_unpaved_area"] = float(
                        row[1] or 0.0
                    )
            except Exception:
                pass
            try:
                row = conn.execute(
                    text(
                        "SELECT AVG(road_impervious_fraction) AS avg_frac "
                        "FROM brewgis.nlcd.overture_road_impervious "
                        "WHERE road_total_area > 0"
                    )
                ).scalar()
                diagnostics["road_surface"]["avg_road_impervious_fraction"] = float(
                    row or 0.0
                )
            except Exception:
                pass

    return diagnostics
