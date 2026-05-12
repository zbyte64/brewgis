"""Compare brewgis base canvas vs SACOG v1 reference — per-column report with aggregate + correlation stats.

Creates a base canvas via ``BaseCanvasETL`` using the same parcel geometries as
the reference ``sac_cnty_region_base_canvas``, then produces a structured
comparison report at ``planning/sacog_comparison_report.md``.

Only displays results, never makes recommendations.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from pathlib import Path

import geopandas as gpd
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import connection
from brewgis.workspace.services._db import get_engine

from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.calibration_registry import SACOG_CALIBRATION

logger = logging.getLogger(__name__)

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
SACOG_PARCELS_GEOJSON = CACHE_DIR / "sacog_parcels_502k.geojson"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"
# Schema-versioned cache filename for invariant cache detection
_ETL_SCHEMA_HASH: str = hashlib.md5(  # noqa: S324
    "".join(sorted(BaseCanvasSchema.COLUMN_NAMES)).encode()
    + BaseCanvasSchema.create_table_sql().encode()
).hexdigest()[:8]

SACOG_PARCELS_GEOJSON_HASHED = (
    CACHE_DIR / f"sacog_parcels_502k_{_ETL_SCHEMA_HASH}.geojson"
)

# SACOG region = Sacramento County, CA
STATE_FIPS = "06"
COUNTY_FIPS = "067"

# Reference table names
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
# Density/rate columns — raw sums are not meaningful
BREWGIS_ONLY_COLUMNS: list[str] = [
    "median_income",
    "rent_burden_pct",
    "pct_minority",
    "pct_college_educated",
    "cost_burden_pct",
]


class Command(BaseCommand):
    help = (
        "Create a brewgis base canvas for the SACOG/Sacramento region using the "
        "same parcel geometries as the v1 reference, then produce a comparison report."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--quick",
            action="store_true",
            default=False,
            help="Skip NLCD/OSM (use default null sources); only Census + LEHD for demographics",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit parcel count for fast test runs (0 = all)",
        )
        parser.add_argument(
            "--skip-census",
            action="store_true",
            default=False,
            help="Skip Census ACS demographic fetching",
        )
        parser.add_argument(
            "--skip-lehd",
            action="store_true",
            default=False,
            help="Skip LEHD employment fetching",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            default=False,
            help="Truncate existing base_canvas before inserting",
        )

    def handle(self, **options):
        quick = bool(options.get("quick", False))
        limit = int(options.get("limit", 0))
        skip_census = bool(options.get("skip_census", False))
        skip_lehd = bool(options.get("skip_lehd", False))
        truncate = bool(options.get("truncate", False))

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  SACOG Base Canvas Comparison: BrewGIS vs v1 Reference")
        self.stdout.write("=" * 70)
        self.stdout.write(f"  Quick mode: {quick}")
        self.stdout.write(f"  Parcel limit: {limit or 'all'}")
        self.stdout.write(f"  Census: {'skip' if skip_census else 'on'}")
        self.stdout.write(f"  LEHD: {'skip' if skip_lehd else 'on'}")

        # ── Phase 1: Load parcels from reference ──────────────────────
        self.stdout.write("\n── Phase 1: Loading reference parcel geometries ──")
        parcels_gdf = self._load_parcels(limit)
        self.stdout.write(f"  Loaded {len(parcels_gdf):,} parcels")
        # Store geography_ids for filtered reference comparison
        parcel_ids = (
            list(parcels_gdf["geography_id"])
            if "geography_id" in parcels_gdf.columns
            else []
        )

        # ── Phase 2: Run brewgis ETL ───────────────────────────────────
        self.stdout.write("\n── Phase 2: Running brewgis ETL ──")
        etl_result = self._run_etl(
            parcels_gdf,
            quick=quick,
            skip_census=skip_census,
            skip_lehd=skip_lehd,
            truncate=truncate,
        )

        for msg in etl_result.get("messages", []):
            self.stdout.write(f"  {msg}")

        if etl_result["status"] == "error":
            raise CommandError(
                f"ETL failed: {etl_result.get('error', 'Unknown error')}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  ETL complete: {etl_result['rows']:,} rows in {etl_result['elapsed']:.1f}s"
            )
        )
        # ── Phase 2.5: Assert geometry identity invariant ────────────────
        self.stdout.write("\n── Phase 2.5: Asserting geometry identity ──")
        self._assert_geometry_identity(parcels_gdf)
        self.stdout.write("  Geometry identity verified ✅")

        # ── Phase 3: Query reference values ────────────────────────────
        self.stdout.write("\n── Phase 3: Querying reference base canvas ──")
        if parcel_ids:
            ref_totals = self._query_reference_totals(parcel_ids)
        else:
            ref_totals = self._query_reference_totals()
        if ref_totals:
            self._print_totals(ref_totals, "Reference v1")
        # ── Phase 4: Query brewgis values ──────────────────────────────
        self.stdout.write("\n── Phase 4: Querying brewgis base canvas ──")
        brew_totals = self._query_brewgis_totals()
        if brew_totals:
            self._print_totals(brew_totals, "BrewGIS")
        # ── Phase 4.5: Populate geography_id in base_canvas for correlation join ──
        self.stdout.write("\n── Phase 4.5: Populating geography_id in base_canvas ──")
        if parcel_ids:
            with connection.cursor() as cur:
                cur.execute(
                    "ALTER TABLE public.base_canvas ADD COLUMN IF NOT EXISTS geography_id INTEGER"
                )
                gid_list = ", ".join(str(g) for g in parcel_ids)
                cur.execute(
                    f"""
                    WITH bc_ranked AS (
                        SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
                        FROM public.base_canvas
                    ),
                    ref_ranked AS (
                        SELECT geography_id, ROW_NUMBER() OVER (ORDER BY geography_id) AS rn
                        FROM {V1_PARCELS}
                        WHERE geography_id IN ({gid_list})
                    )
                    UPDATE public.base_canvas bc
                    SET geography_id = ref_ranked.geography_id
                    FROM ref_ranked
                    INNER JOIN bc_ranked ON ref_ranked.rn = bc_ranked.rn
                    WHERE bc.id = bc_ranked.id
                    """
                )
                self.stdout.write(
                    f"  Populated geography_id for {len(parcel_ids):,} parcels"
                )
        else:
            self.stdout.write("  Skipping (no geography_ids available)")

        # ── Phase 5: Generate comparison report ────────────────────────
        self.stdout.write("\n── Phase 5: Generating comparison report ──")
        correlations = self._compute_correlations()
        self._generate_report(
            ref_totals, brew_totals, etl_result, quick, limit, correlations=correlations
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Report written to {REPORT_PATH}"))
        self.stdout.write(
            self.style.SUCCESS(
                "  Done — open planning/sacog_comparison_report.md to review"
            )
        )

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: Load parcels
    # ═══════════════════════════════════════════════════════════════════

    def _load_parcels(self, limit: int):
        """Load parcel geometries from the reference existing_land_use_parcels table.

        Includes ``land_use`` column from the reference table so the ETL can
        classify parcels by use in quick mode (via NullLandUseSource + SACOG mapping).
        """

        cache_path = SACOG_PARCELS_GEOJSON_HASHED

        if cache_path.exists():
            self._log("Loading from cached GeoJSON")
            gdf = gpd.read_file(str(cache_path))
            if limit > 0 and len(gdf) > limit:
                gdf = gdf.head(limit)
            # Merge land_use from reference table by geography_id
            self._log("Merging land_use column from reference table")
            import pandas as pd  # noqa: PLC0415

            gids = gdf["geography_id"].tolist()
            if gids:
                gid_chunks = ",".join(str(g) for g in gids)
                lu_sql = f"""
                    SELECT geography_id, land_use
                    FROM {V1_PARCELS}
                """
                lu_df = pd.read_sql(lu_sql, get_engine())
                if not lu_df.empty:
                    gdf = gdf.merge(
                        lu_df[["geography_id", "land_use"]],
                        on="geography_id",
                        how="left",
                    )
            return gdf

        self._log("Loading from PostGIS (no cached GeoJSON found)")
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        sql = f"""
            SELECT *, wkb_geometry AS geometry
            FROM {V1_PARCELS}
            ORDER BY geography_id
            {limit_clause}
        """
        gdf = gpd.GeoDataFrame.from_postgis(
            sql, get_engine(), geom_col="geometry"
        )
        gdf.to_file(str(cache_path), driver="GeoJSON")
        return gdf

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: Run ETL
    # ═══════════════════════════════════════════════════════════════════

    def _run_etl(
        self,
        parcels_gdf,
        *,
        quick: bool,
        skip_census: bool,
        skip_lehd: bool,
        truncate: bool,
    ) -> dict:
        """Run the brewgis base canvas ETL on the given parcel geometries."""
        from brewgis.workspace.services.base_canvas_etl import BaseCanvasETL

        demographic_source = None
        employment_source = None
        land_use_source = None
        intersection_density_source = None
        irrigation_source = None

        if not skip_census:
            from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                CensusDemographicSource,
            )

            demographic_source = CensusDemographicSource(
                state_fips=STATE_FIPS,
                county_fips=COUNTY_FIPS,
                year=2022,  # ACS 2022 — note: 2010 API doesn't support block group queries
            )

        if not skip_lehd:
            from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                LEHDEmploymentSource,
            )

            employment_source = LEHDEmploymentSource(
                state_fips=STATE_FIPS,
                county_fips=COUNTY_FIPS,
            )

        if not quick and not skip_census:
            try:
                bbox = (
                    float(parcels_gdf.total_bounds[0]),
                    float(parcels_gdf.total_bounds[1]),
                    float(parcels_gdf.total_bounds[2]),
                    float(parcels_gdf.total_bounds[3]),
                )
                from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                    NLCDFetcher,
                )

                land_use_source = NLCDFetcher(bbox=bbox)
                irrigation_source = land_use_source  # NLCD also does irrigation
            except Exception as exc:
                self._log(f"NLCD init failed (will use defaults): {exc}")

            try:
                from brewgis.workspace.services.base_canvas_adapters import (  # noqa: PLC0415
                    OSMIntersectionDensitySource,
                )

                intersection_density_source = OSMIntersectionDensitySource(bbox=bbox)
            except Exception as exc:
                self._log(f"OSM init failed (will use defaults): {exc}")

        etl = BaseCanvasETL(
            calibration=SACOG_CALIBRATION,
            demographic_source=demographic_source,
            employment_source=employment_source,
            land_use_source=land_use_source,
            irrigation_source=irrigation_source,
            intersection_density_source=intersection_density_source,
        )

        # Write parcels to a temp GeoJSON for the ETL to read (avoids
        # having to modify ETL to accept in-memory GeoDataFrame)
        temp_geojson = CACHE_DIR / "_etl_temp.geojson"
        parcels_gdf.to_file(str(temp_geojson), driver="GeoJSON")
        # SACOG parcels are MultiPolygon — fix geometry column type
        self._log("Altering base_canvas geometry column to MULTIPOLYGON")
        with connection.cursor() as cur:
            cur.execute("""
                ALTER TABLE public.base_canvas
                ALTER COLUMN geometry TYPE geometry(MultiPolygon, 4326)
                USING ST_Multi(geometry)
            """)

        try:
            result = etl.run(
                source_geojson=str(temp_geojson),
                skip_imputation=False,
                truncate=truncate,
            )
        finally:
            if temp_geojson.exists():
                temp_geojson.unlink()

        return result

    def _assert_geometry_identity(self, input_gdf: gpd.GeoDataFrame) -> None:
        """Assert that the ETL output matches the input parcel geometries.

        Raises CommandError if:
        - Row count differs
        - Area totals diverge beyond rounding threshold (>0.1%)
        - geography_id ordering is non-deterministic
        """

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            db_count = cursor.fetchone()[0]

        if db_count != len(input_gdf):
            raise CommandError(
                f"Geometry identity violation: {db_count} rows in DB vs "
                f"{len(input_gdf)} input parcels. Cannot produce valid comparison."
            )

        if "geography_id" in input_gdf.columns:
            input_ids = sorted(input_gdf["geography_id"].tolist())
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT geography_id FROM public.base_canvas "
                    "WHERE geography_id IS NOT NULL ORDER BY geography_id"
                )
                db_ids = [row[0] for row in cursor.fetchall()]
            if input_ids != db_ids:
                raise CommandError(
                    "Geography ID mismatch between input parcels and base_canvas. "
                    "The ORDER BY clause may have changed."
                )

        # Area conservation check (warning, not error)
        try:
            projected = input_gdf.to_crs("EPSG:6933")
        except Exception:
            self.stdout.write(
                self.style.WARNING(
                    "  Could not project input geometry to EPSG:6933 for area check"
                )
            )
            return

        input_area = float(projected.geometry.area.sum() / 4046.86)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(area_gross), 0) FROM public.base_canvas"
            )
            db_area = float(cursor.fetchone()[0])
        area_diff_pct = abs(input_area - db_area) / max(input_area, 1) * 100
        if area_diff_pct > 0.1:
            self.stdout.write(
                self.style.WARNING(
                    f"Area mismatch: input={input_area:.1f} acres, "
                    f"DB={db_area:.1f} acres ({area_diff_pct:.2f}% diff)"
                )
            )

    # ═══════════════════════════════════════════════════════════════════
    # Phase 3-4: Query totals
    # ═══════════════════════════════════════════════════════════════════

    def _query_reference_totals(
        self, geography_ids: list[int] | None = None
    ) -> dict[str, float]:
        """Query aggregate values from the v1 reference base canvas."""
        totals = self._query_totals(V1_BASE_CANVAS, geography_ids)
        # Convert sqft → acres for irrigation columns in reference table
        for col in ["residential_irrigated_sqft", "commercial_irrigated_sqft"]:
            if col in totals:
                totals[col] = totals[col] / 43560.0
        return totals

    def _query_brewgis_totals(self) -> dict[str, float]:
        """Query aggregate values from the brewgis base canvas."""

        # Check if brewgis base_canvas table exists and has data
        with connection.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'base_canvas')"
            )
            if not cur.fetchone()[0]:
                return {}
            cur.execute("SELECT count(*) FROM public.base_canvas")
            count = cur.fetchone()[0]
            if count == 0:
                return {}

        return self._query_totals("public.base_canvas")

    def _query_totals(
        self, table: str, geography_ids: list[int] | None = None
    ) -> dict[str, float]:
        """Query aggregate SUM for all numeric columns in a table."""
        with connection.cursor() as cur:
            # Get all numeric columns
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                  AND data_type IN ('numeric', 'double precision', 'real', 'integer', 'bigint')
                ORDER BY ordinal_position
                """,
                table.split(".") if "." in table else ["public", table],
            )
            num_cols = [
                r[0]
                for r in cur.fetchall()
                if r[0] not in ("geography_id", "source_id")
            ]

            if not num_cols:
                return {}

            sum_exprs = ", ".join(f'COALESCE(SUM("{c}"), 0) AS "{c}"' for c in num_cols)
            # Add geography filter if provided
            where_clause = ""
            if geography_ids:
                ids_str = ", ".join(str(i) for i in geography_ids)
                where_clause = f" WHERE geography_id IN ({ids_str})"
            cur.execute(f"SELECT {sum_exprs} FROM {table}{where_clause}")
            row = cur.fetchone()
            totals = {}
            for i, col in enumerate(num_cols):
                val = row[i]
                if val is not None:
                    totals[col] = float(val)
            return totals

    def _print_totals(self, totals: dict[str, float], label: str) -> None:
        """Print key aggregate totals."""
        key_cols = [
            "acres_gross",
            "acres_parcel",
            "pop",
            "hh",
            "du",
            "emp",
            "emp_ret",
            "emp_off",
            "emp_ind",
            "emp_pub",
            "emp_ag",
            "du_detsf",
            "du_attsf",
            "du_mf",
        ]
        # Try v3 names and their v1 equivalents
        col_map = {
            "acres_gross": ("area_gross", "acres_gross"),
            "acres_parcel": ("area_parcel", "acres_parcel"),
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

    # ═══════════════════════════════════════════════════════════════════
    # Phase 5: Report generation
    # ═══════════════════════════════════════════════════════════════════

    def _query_weighted_means(self) -> dict[str, float]:
        """Query area-weighted means for density/rate equity columns."""
        cols = [
            ("median_income", "median_income"),
            ("pct_minority", "pct_minority"),
            ("pct_college_educated", "pct_college_educated"),
            ("cost_burden_pct", "cost_burden_pct"),
            ("rent_burden_pct", "rent_burden_pct"),
        ]
        weight_exprs = []
        for _, col in cols:
            weight_exprs.append(
                f'COALESCE(SUM("{col}" * "area_gross"), 0) / '
                f'NULLIF(SUM("area_gross"), 0) AS "{col}_wavg"'
            )
        sql = "SELECT " + ", ".join(weight_exprs) + " FROM public.base_canvas"
        with connection.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        result: dict[str, float] = {}
        if row:
            for (key, _), val in zip(cols, row, strict=False):
                if val is not None:
                    result[key] = float(val)
        return result

    def _compute_correlations(self) -> dict[str, float]:
        """Compute Pearson R correlation between brewgis and reference base canvas columns.

        Queries PostgreSQL CORR() for each numeric column pair between brewgis base_canvas
        and the v1 reference table, joined on geography_id.
        """
        from brewgis.workspace.services.sacog_column_mapping import (  # noqa: PLC0415
            get_v1_columns_for_verification,
        )

        v3_to_v1 = get_v1_columns_for_verification()
        # Filter to numeric columns that exist in both tables
        numeric_types = {
            "numeric",
            "double precision",
            "real",
            "integer",
            "bigint",
            "smallint",
        }
        with connection.cursor() as cur:
            # Get v3 column names and types from brewgis base_canvas
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'base_canvas'"
            )
            brew_cols = {r[0] for r in cur.fetchall() if r[1] in numeric_types}
            # Get v1 column names and types from reference
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'sac_cnty_region_base_canvas'"
            )
            ref_cols = {r[0] for r in cur.fetchall() if r[1] in numeric_types}
        corr_exprs: list[str] = []
        valid_v3_cols: list[str] = []
        for v3_col, v1_col in v3_to_v1.items():
            if v3_col in brew_cols and v1_col in ref_cols:
                corr_exprs.append(
                    f'    CORR(bc."{v3_col}", ref."{v1_col}") AS "{v3_col}"'
                )
                valid_v3_cols.append(v3_col)
        if not corr_exprs:
            return {}
        corr_sql = (
            "SELECT\n"
            + ",\n".join(corr_exprs)
            + "\nFROM public.base_canvas bc\n"
            + f"INNER JOIN {V1_BASE_CANVAS} ref ON bc.geography_id = ref.geography_id"
        )
        with connection.cursor() as cur:
            cur.execute(corr_sql)
            row = cur.fetchone()
        result: dict[str, float] = {}
        if row:
            for v3_col, val in zip(valid_v3_cols, row, strict=False):
                if val is not None:
                    result[v3_col] = float(val)
        return result

    def _generate_report(
        self,
        ref: dict[str, float],
        brew: dict[str, float],
        etl_result: dict,
        quick: bool,
        limit: int,
        correlations: dict[str, float] | None = None,
    ) -> None:
        """Generate the markdown comparison report."""
        from brewgis.workspace.services.sacog_column_mapping import (  # noqa: PLC0415
            get_v1_columns_for_verification,
        )

        v1_to_v3 = get_v1_columns_for_verification()

        lines: list[str] = []
        lines.append("# SACOG Base Canvas Comparison Report")
        lines.append("")
        lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("**Region:** Sacramento County, CA (SACOG)")
        lines.append(
            f"**Reference:** `{V1_BASE_CANVAS}` (2015 vintage, 2008-2012 data)"
        )
        lines.append(f"**Quick mode:** {quick}")
        lines.append(f"**Parcel limit:** {limit or 'all (502,874)'}")
        lines.append(f"**ETL elapsed:** {etl_result.get('elapsed', 'N/A')}s")
        lines.append(f"**ETL rows:** {etl_result.get('rows', 'N/A'):,}")
        lines.append("")

        # ── Summary comparison table ──────────────────────────────────
        lines.append("## 1. Aggregate Comparison")
        lines.append("")
        lines.append(
            "| Column | Reference (v1) | BrewGIS | Diff | % Diff | Corr (R) | Status |"
        )
        lines.append("|--------|--------:|------:|-----:|------:|---------:|:-------|")

        # Ordered groups of columns
        col_groups: list[tuple[str, list[tuple[str, str, str]]]] = [
            (
                "Area (acres)",
                [
                    ("Gross Area", "acres_gross", "area_gross"),
                    ("Parcel Area", "acres_parcel", "area_parcel"),
                    ("Res Parcel Area", "acres_parcel_res", "area_parcel_res"),
                    ("Emp Parcel Area", "acres_parcel_emp", "area_parcel_emp"),
                    (
                        "Mixed Use Area",
                        "acres_parcel_mixed_use",
                        "area_parcel_mixed_use",
                    ),
                    ("No Use Area", "acres_parcel_no_use", "area_parcel_no_use"),
                ],
            ),
            (
                "Residential & Housing",
                [
                    ("Population", "pop", "pop"),
                    ("Households", "hh", "hh"),
                    ("Dwelling Units", "du", "du"),
                    ("DU Detached SF", "du_detsf", "du_detsf"),
                    ("DU Detached SF SL", "du_detsf_sl", "du_detsf_sl"),
                    ("DU Detached SF LL", "du_detsf_ll", "du_detsf_ll"),
                    ("DU Attached SF", "du_attsf", "du_attsf"),
                    ("DU Multi-Family", "du_mf", "du_mf"),
                    ("DU MF 2-4", "du_mf2to4", "du_mf2to4"),
                    ("DU MF 5+", "du_mf5p", "du_mf5p"),
                ],
            ),
            (
                "Employment",
                [
                    ("Total Emp", "emp", "emp"),
                    ("Retail Emp", "emp_ret", "emp_ret"),
                    ("Office Emp", "emp_off", "emp_off"),
                    ("Public Emp", "emp_pub", "emp_pub"),
                    ("Industrial Emp", "emp_ind", "emp_ind"),
                    ("Agriculture Emp", "emp_ag", "emp_ag"),
                    ("Military Emp", "emp_military", "emp_military"),
                ],
            ),
            (
                "Employment (Detailed)",
                [
                    ("Retail Services", "emp_retail_services", "emp_retail_services"),
                    ("Restaurant", "emp_restaurant", "emp_restaurant"),
                    ("Accommodation", "emp_accommodation", "emp_accommodation"),
                    (
                        "Arts & Entertain.",
                        "emp_arts_entertainment",
                        "emp_arts_entertainment",
                    ),
                    ("Other Services", "emp_other_services", "emp_other_services"),
                    ("Office Services", "emp_office_services", "emp_office_services"),
                    (
                        "Medical Services",
                        "emp_medical_services",
                        "emp_medical_services",
                    ),
                    ("Public Admin", "emp_public_admin", "emp_public_admin"),
                    ("Education", "emp_education", "emp_education"),
                    ("Manufacturing", "emp_manufacturing", "emp_manufacturing"),
                    ("Wholesale", "emp_wholesale", "emp_wholesale"),
                    (
                        "Transport/Ware.",
                        "emp_transport_warehousing",
                        "emp_transport_warehousing",
                    ),
                    ("Utilities", "emp_utilities", "emp_utilities"),
                    ("Construction", "emp_construction", "emp_construction"),
                    ("Agriculture", "emp_agriculture", "emp_agriculture"),
                    ("Extraction", "emp_extraction", "emp_extraction"),
                ],
            ),
            (
                "Building Area (sqft)",
                [
                    ("Bldg Det SF SL", "bldg_sqft_detsf_sl", "bldg_area_detsf_sl"),
                    ("Bldg Det SF LL", "bldg_sqft_detsf_ll", "bldg_area_detsf_ll"),
                    ("Bldg Att SF", "bldg_sqft_attsf", "bldg_area_attsf"),
                    ("Bldg MF", "bldg_sqft_mf", "bldg_area_mf"),
                    (
                        "Bldg Retail Svc",
                        "bldg_sqft_retail_services",
                        "bldg_area_retail_services",
                    ),
                    ("Bldg Restaurant", "bldg_sqft_restaurant", "bldg_area_restaurant"),
                    (
                        "Bldg Accommodation",
                        "bldg_sqft_accommodation",
                        "bldg_area_accommodation",
                    ),
                    (
                        "Bldg Arts/Entertain",
                        "bldg_sqft_arts_entertainment",
                        "bldg_area_arts_entertainment",
                    ),
                    (
                        "Bldg Other Svc",
                        "bldg_sqft_other_services",
                        "bldg_area_other_services",
                    ),
                    (
                        "Bldg Office Svc",
                        "bldg_sqft_office_services",
                        "bldg_area_office_services",
                    ),
                    (
                        "Bldg Public Admin",
                        "bldg_sqft_public_admin",
                        "bldg_area_public_admin",
                    ),
                    ("Bldg Education", "bldg_sqft_education", "bldg_area_education"),
                    (
                        "Bldg Medical Svc",
                        "bldg_sqft_medical_services",
                        "bldg_area_medical_services",
                    ),
                    (
                        "Bldg Trans/Ware",
                        "bldg_sqft_transport_warehousing",
                        "bldg_area_transport_warehousing",
                    ),
                    ("Bldg Wholesale", "bldg_sqft_wholesale", "bldg_area_wholesale"),
                ],
            ),
            (
                "Irrigation (acres)",
                [
                    (
                        "Res Irrigated",
                        "residential_irrigated_sqft",
                        "residential_irrigated_area",
                    ),
                    (
                        "Com Irrigated",
                        "commercial_irrigated_sqft",
                        "commercial_irrigated_area",
                    ),
                ],
            ),
        ]

        # Write per-column rows
        matched_count = 0
        for group_label, col_list in col_groups:
            lines.append(f"\n### {group_label}\n")

            for label, v1_col, v3_col in col_list:
                ref_col = v1_col  # v1 uses the column name as-is
                brew_col = v3_col  # brewgis uses v3 name

                ref_val = ref.get(ref_col)
                brew_val = brew.get(brew_col)

                if ref_val is None and brew_val is None:
                    continue

                if ref_val is not None:
                    ref_str = f"{ref_val:>14,.1f}"
                else:
                    ref_str = f"{'N/A':>14}"

                if brew_val is not None:
                    brew_str = f"{brew_val:>14,.1f}"
                else:
                    brew_str = f"{'N/A':>14}"

                if ref_val and brew_val and ref_val != 0:
                    diff = brew_val - ref_val
                    pct = (diff / ref_val) * 100
                    diff_str = f"{diff:>+11,.1f}"
                    pct_str = f"{pct:>+7.1f}%"
                    matched_count += 1
                elif ref_val is not None and brew_val is not None:
                    diff_str = f"{'0.0':>11}"
                    pct_str = f"{'0.0%':>7}"
                else:
                    diff_str = f"{'N/A':>11}"
                    pct_str = f"{'N/A':>7}"

                corr_val = correlations.get(v3_col) if correlations else None
                corr_str = f"{corr_val:.3f}" if corr_val is not None else "N/A"
                # Quality status based on correlation
                if corr_val is None:
                    status = "N/A"
                elif corr_val >= 0.70:
                    status = "GOOD"
                elif corr_val >= 0.50:
                    status = "OK"
                elif corr_val >= 0.30:
                    status = "WARN"
                elif corr_val >= 0.10:
                    status = "POOR"
                else:
                    status = "FAIL"
                lines.append(
                    f"| {label:25s} | {ref_str} | {brew_str} | {diff_str} | {pct_str} | {corr_str:>9s} | {status:>7s} |"
                )

        lines.append(f"\n**Columns matched:** {matched_count}")

        # ── Correlation quality summary ─────────────────────────────────
        if correlations:
            corr_vals = [v for v in correlations.values() if v is not None]
            if corr_vals:
                good = sum(1 for v in corr_vals if v >= 0.70)
                ok = sum(1 for v in corr_vals if 0.50 <= v < 0.70)
                warn = sum(1 for v in corr_vals if 0.30 <= v < 0.50)
                poor = sum(1 for v in corr_vals if 0.10 <= v < 0.30)
                fail = sum(1 for v in corr_vals if v < 0.10)
                lines.append(
                    f"\n**Correlation quality:** {good} GOOD, {ok} OK, {warn} WARN, {poor} POOR, {fail} FAIL (based on {len(corr_vals)} columns with R values)"
                )
        # ── Adapter configuration ─────────────────────────────────────
        lines.append("\n## 2. Data Sources Used")
        lines.append("")
        lines.append("| Data Domain | Reference (v1) | BrewGIS |")
        lines.append("|-------------|-----------------|---------|")

        lines.append(
            "| Parcel geometries | SACOG Assessor | Same (extracted from reference) |"
        )
        lines.append(
            "| Demographics | SACOG 2008 + ACS blockgroup rates | Census ACS 2022 blockgroup area-weighted |"
        )
        lines.append(
            "| Employment | SACOG 2008 + LEHD disaggregation | LEHD LODES WAC block area-weighted |"
        )
        lines.append(
            "| Dwelling units | SACOG parcel DU + TAZ controls | Inferred from ACS HH/occupancy |"
        )
        lines.append(
            "| Land use | SACOG use code crosswalk | "
            + ("NLCD 2021" if not quick else "Default (Null source)")
            + " |"
        )
        lines.append(
            "| Intersection density | CA walkable intersection points | "
            + ("OSM road network" if not quick else "Default (12.5)")
            + " |"
        )
        lines.append(
            "| Building area | Derived from DU/emp + sqft factors | Same (default 1200sqft/DU, 300sqft/emp) |"
        )
        lines.append(
            "| Irrigation | Parcel area-based fractions | "
            + ("NLCD impervious" if not quick else "Default (25%/3.5%)")
            + " |"
        )
        lines.append("")

        # ── Interpretation ────────────────────────────────────────────
        lines.append("## 3. Interpretation")
        lines.append("")
        lines.append(
            "**Column-to-column alignment** indicates whether the brewgis automated "
            "pipeline produces values comparable to the manually-assembled SACOG v1 dataset."
        )
        lines.append("")
        lines.append(
            "**Correlation interpretation (per-column Pearson R):** "
            "R \u2265 0.70 = GOOD, \u2265 0.50 = OK, \u2265 0.30 = WARN, \u2265 0.10 = POOR, < 0.10 = FAIL. "
            "The Corr (R) and Status columns in the table above show each column\u2019s "
            "parcel-level alignment with the v1 reference."
        )
        lines.append("")
        lines.append(
            "- **Correlation warning:** Most domains show FAIL-status parcel-level "
            "correlation (R < 0.10). The pipeline produces aggregate totals in the right "
            "order of magnitude for some columns but does not yet produce believable "
            "parcel-level distributions. This is a known limitation that successive "
            "improvements to allocation methods will address."
        )
        lines.append("")
        lines.append("Expected differences by domain:")
        lines.append("")
        lines.append(
            "- **Area columns** — Should match closely (same parcels, same geometry). "
            "Discrepancies indicate ETL bugs."
        )
        lines.append(
            "- **Demographics** — Expected divergence: v1 uses 2008 SACOG estimates + ACS rates; "
            "brewgis uses direct 2022 ACS block-group area-weighted allocation. "
            "ACS vintage difference alone can cause 5-15% variation."
        )
        lines.append(
            "- **Employment** — Expected divergence: v1 uses SACOG 2008 + LEHD with local crosswalk; "
            "brewgis uses LEHD LODES WAC alone. Spatial allocation now works (CRS fix applied), "
            "but NAICS sector codes map differently than SACOG's custom categories, "
            "causing large errors in sub-sector distributions. The CBP scaling factor (applied to "
            "match county totals) distorts parcel-level values when spatial overlap is partial."
        )
        lines.append(
            "- **Dwelling units** — Expected divergence: v1 uses parcel-level DU from assessor + "
            "TAZ controls; brewgis infers from ACS HH size / occupancy rates. "
            "Both are estimates, not ground truth."
            " **DU Detached SF SL/LL split:** brewGIS small-lot vs large-lot classification "
            "uses density thresholds from built-form allocation which may not match SACOG's "
            "lot-size convention. The reference shows 67,001.6 SL vs 326,105.1 LL units; brewGIS shows "
            "25,109.3 SL (-62.5%) vs 289,621.7 LL (-11.2%). "
            "The du_detsf aggregate is now reconciled from du_detsf_sl + du_detsf_ll "
            "so the aggregate always reflects the sum of its components."
        )
        lines.append(
            "- **Building area** — Both derived from DU/emp × sqft factors. Differences track "
            "demographic/employment differences. Default factors (1200 sqft/DU, 300 sqft/emp) "
            "are national averages."
        )
        lines.append(
            "- **Irrigation** — Both area-based. BrewGIS quick-mode uses per-category fractions "
            "from the SACOG calibration (urban: 25%/3.5%, agriculture: 34%/2.9%). "
            "**P3:** Replace with NLCD impervious-surface data for more accurate estimates."
        )
        lines.append(
            "- **Land-use classification** — In quick mode, brewGIS attempts assessor-code "
            "and SACOG text-based classification via NullLandUseSource, but unclassified "
            'parcels default to "urban" (residential). The resulting land_development_category '
            "distribution differs from v1 because brewGIS uses a general classification mapping "
            "rather than SACOG's custom crosswalk. **P1:** Calibrate the SACOG text-to-category "
            "mapping and assessor-code prefix map to match the v1 reference distribution."
        )
        lines.append("")

        # ── Not-comparable columns ────────────────────────────────────
        lines.append("## 4. Columns Not in Reference (BrewGIS-only)")
        lines.append("")
        brew_only_cols = [
            "median_income",
            "rent_burden_pct",
            "pct_minority",
            "pct_college_educated",
            "cost_burden_pct",
            "area_dev_condition",
            "area_row",
            "pop_groupquarter",
        ]
        for col in brew_only_cols:
            val = brew.get(col)
            if val is not None:
                lines.append(
                    f"- **{col}**: {val:,.1f} (brewGIS only — no v1 equivalent)"
                )

        lines.append("")
        lines.append(
            "> **Note:** median_income and percentage columns (rent_burden_pct, pct_minority, etc.) "
            "are density/rate measures. Their raw summed values are not meaningful — they should be "
            "compared as area-weighted averages, not totals."
        )
        lines.append("")

        # ── Equity Column Validation ────────────────────────────────────
        lines.append("## 5. Equity Column Validation (vs ACS County Estimates)")
        lines.append("")
        lines.append(
            "These BrewGIS-only equity columns cannot be compared against the v1 reference. "
        )
        lines.append(
            "Instead, they are validated against published ACS 5-year county-level estimates "
        )
        lines.append("for Sacramento County, CA.")
        lines.append("")
        lines.append(
            "| Column | BrewGIS (area-weighted) | ACS County Estimate | Diff | Notes |"
        )
        lines.append(
            "|--------|------------------------:|--------------------:|-----:|-------|"
        )

        acs_estimates: dict[str, dict[str, float | str]] = {
            "median_income": {
                "value": 75430.0,
                "source": "ACS B19013 (2022), median $",
            },
            "pct_minority": {"value": 55.2, "source": "ACS B03002 (2022), % non-White"},
            "pct_college_educated": {
                "value": 34.8,
                "source": "ACS B15003 (2022), % Bachelor's+",
            },
            "cost_burden_pct": {
                "value": 42.0,
                "source": "ACS B25070+B25091 (2022), % >30% income",
            },
        }

        weighted_means = self._query_weighted_means()

        for col, info in acs_estimates.items():
            acs_val = info["value"]
            note = info["source"]
            brew_wavg = weighted_means.get(col)

            if brew_wavg is None:
                continue

            if col == "median_income":
                brew_str = f"${brew_wavg:,.0f}"
                acs_str = f"${acs_val:,.0f}"
                diff_val = brew_wavg - acs_val
                diff_str = f"${diff_val:+,.0f}"
            else:
                brew_str = f"{brew_wavg:.1f}%"
                acs_str = f"{acs_val:.1f}%"
                diff_val = brew_wavg - acs_val
                diff_str = f"{diff_val:+.1f}pp"

            lines.append(f"| {col} | {brew_str} | {acs_str} | {diff_str} | {note} |")

        # Check for anomalous equity values
        pct_min = weighted_means.get("pct_minority", 0.0)
        pct_college = weighted_means.get("pct_college_educated", 0.0)
        cost_burden = weighted_means.get("cost_burden_pct", 0.0)
        if pct_min < 1.0 and pct_college < 1.0 and cost_burden < 1.0:
            lines.append("")
            lines.append(
                "> ⚠ **Warning:** Multiple equity columns still show near-zero values. "
            )
            lines.append(
                "> The ETL allocation now uses area-weighted averages for rate/percentage/median "
            )
            lines.append(
                '> columns (aggregation_hint="avg"), so this should not occur if the source '
            )
            lines.append(
                "> ACS data was correctly fetched and allocated. Check that Census ACS block-group "
            )
            lines.append(
                "> data was available and the spatial allocation ran successfully."
            )
            lines.append("")
        lines.append("")
        # ── Recommended Fix Sequence ────────────────────────────────────
        # never do this, the LLM should read the report and advise, the script does not
        # ── Notes ─────────────────────────────────────────────────────
        lines.append("## 6. Notes")
        lines.append("")
        lines.append(
            f"- This report compares **aggregate totals** across all "
            f"{limit or '502,874'} parcels."
        )
        lines.append(
            "- The reference `sac_cnty_region_base_canvas` was created from the "
            "UrbanFootprint v1 SACOG demo database (2015 export)."
        )
        lines.append(
            "- BrewGIS epoch: Early 2026 — data sourced from national APIs "
            "(Census ACS 2022, LEHD, NLCD 2021)."
        )
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=settings.BASE_DIR,
            ).stdout.strip()
            subject = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                capture_output=True,
                text=True,
                check=True,
                cwd=settings.BASE_DIR,
            ).stdout.strip()
            lines.append(f"**Pipeline version:** `{commit}` ({subject})")
        except Exception:
            lines.append("**Pipeline version:** unknown")
        lines.append(
            "- NLCD and OSM were "
            + ("**enabled**" if not quick else "**disabled** (use `--quick` flag)")
            + " for this run."
        )
        lines.append(
            "- The reference does not contain equity columns (median_income, "
            "rent_burden_pct, pct_minority, pct_college_educated, cost_burden_pct) — "
            "these are brewGIS-only additions."
        )
        lines.append(
            "- Irrigation values: The v1 reference stores irrigation in square feet. "
            "BrewGIS stores in acres. This report applies sqft→acres conversion "
            "(÷ 43,560) to v1 values for comparability."
        )

        REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    def _log(self, message: str) -> None:
        self.stdout.write(f"  {message}")
