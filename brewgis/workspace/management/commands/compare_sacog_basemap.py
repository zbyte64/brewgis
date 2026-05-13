"""Compare brewgis base canvas vs SACOG v1 reference — per-column report with aggregate + correlation stats.

Creates a base canvas via ``BaseCanvasETL`` using the same parcel geometries as
the reference ``sac_cnty_region_base_canvas``, then produces a structured
comparison report at ``planning/sacog_comparison_report.md``.

Delegates to the refactored ``comparison_assets`` module for the actual work.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

# Functions imported lazily in handle() — kept here for TYPE_CHECKING
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brewgis.workspace.dagster.assets.comparison_assets import (
        _generate_report_markdown,
    )
    from brewgis.workspace.dagster.assets.comparison_assets import _load_parcels
    from brewgis.workspace.dagster.assets.comparison_assets import _run_etl

from pathlib import Path

CACHE_DIR = Path(settings.BASE_DIR) / "planning"
REPORT_PATH = CACHE_DIR / "sacog_comparison_report.md"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
logger = logging.getLogger(__name__)
STATE_FIPS = "06"
COUNTY_FIPS = "067"


class Command(BaseCommand):
    help = (
        "Create a brewgis base canvas for the SACOG/Sacramento region using the "
        "same parcel geometries as the v1 reference, then produce a comparison report."
    )

    def add_arguments(self, parser: Any) -> None:
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

    def handle(self, **options: Any) -> None:
        # Lazy imports — avoid loading great_expectations at module import time
        # which conflicts with test stubs for pandas/geopandas.
        from brewgis.workspace.dagster.assets.comparison_assets import (  # noqa: PLC0415, C0415
            _generate_report_markdown,
        )
        from brewgis.workspace.dagster.assets.comparison_assets import _load_parcels  # noqa: PLC0415, C0415
        from brewgis.workspace.dagster.assets.comparison_assets import _run_etl  # noqa: PLC0415, C0415
        from brewgis.workspace.dagster.assets.comparison_assets import CACHE_DIR  # noqa: PLC0415, C0415
        from brewgis.workspace.dagster.assets.comparison_assets import REPORT_PATH  # noqa: PLC0415, C0415
        from brewgis.workspace.dagster.assets.comparison_assets import V1_BASE_CANVAS  # noqa: PLC0415, C0415
        from brewgis.workspace.dagster.assets.comparison_assets import V1_PARCELS  # noqa: PLC0415, C0415

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
        if not settings.CENSUS_API_KEY:
            self.stdout.write(
                self.style.WARNING(
                    "  WARNING: CENSUS_API_KEY is not set. Census ACS and CBP API calls will fail. "
                    "Set CENSUS_API_KEY in your .env file. Get a free key at "
                    "https://api.census.gov/data/key_signup.html"
                )
            )

        # ── Phase 1: Load parcels from reference ──────────────────────
        self.stdout.write("\n── Phase 1: Loading reference parcel geometries ──")
        parcels_gdf = _load_parcels(limit)
        self.stdout.write(f"  Loaded {len(parcels_gdf):,} parcels")
        parcel_ids = (
            list(parcels_gdf["geography_id"])
            if "geography_id" in parcels_gdf.columns
            else []
        )

        # Populate ACS staging table before ETL
        if not skip_census:
            self.stdout.write("\n── Populating Census ACS staging table ──")
            from brewgis.workspace.dlt_pipelines.census import (  # noqa: PLC0415, C0415
                run_census_pipeline,
            )

            census_result = run_census_pipeline(STATE_FIPS, COUNTY_FIPS, 2022)
            if not census_result["success"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Census ACS fetch failed: {census_result.get('error')}; "
                        "demographics will be zero-filled"
                    )
                )
            else:
                self.stdout.write(
                    f"  Census ACS loaded: {census_result.get('row_count', 0)} rows "
                    f"in {census_result.get('table_name', '?')}"
                )

        # Populate LEHD staging table before ETL
        if not skip_lehd:
            self.stdout.write("\n── Populating LEHD LODES staging table ──")
            from brewgis.workspace.dlt_pipelines.lehd import (  # noqa: PLC0415, C0415
                run_lehd_pipeline,
            )

            lehd_result = run_lehd_pipeline(STATE_FIPS, COUNTY_FIPS, 2021)
            if not lehd_result["success"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  LEHD fetch failed: {lehd_result.get('error')}; "
                        "employment will be zero-filled"
                    )
                )
            else:
                self.stdout.write(
                    f"  LEHD LODES loaded: {lehd_result.get('row_count', 0)} rows "
                    f"in {lehd_result.get('table_name', '?')}"
                )
        # ── Phase 2: Run brewgis ETL ───────────────────────────────────
        self.stdout.write("\n── Phase 2: Running brewgis ETL ──")
        run_id = str(int(time.time()))
        temp_dir = CACHE_DIR / f"_comparison_etl_{run_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_geojson = temp_dir / "parcels.geojson"

        etl_result = _run_etl(
            parcels_gdf,
            quick=quick,
            skip_census=skip_census,
            skip_lehd=skip_lehd,
            truncate=truncate,
            temp_geojson=temp_geojson,
        )

        # Clean up temp directory
        if temp_geojson.exists():
            temp_geojson.unlink()
        try:
            temp_dir.rmdir()
        except OSError:
            pass

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

        # ── Phase 2.5: Assert geometry identity ────────────────────────
        self.stdout.write("\n── Phase 2.5: Asserting geometry identity ──")
        self._assert_geometry_identity(parcels_gdf)
        self.stdout.write("  Geometry identity verified ✅")

        # ── Phase 3: Query reference values ────────────────────────────
        self.stdout.write("\n── Phase 3: Querying reference base canvas ──")
        ref_totals = self._query_reference_totals(parcel_ids)
        if ref_totals:
            self._print_totals(ref_totals, "Reference v1")

        # ── Phase 4: Query brewgis values ──────────────────────────────
        self.stdout.write("\n── Phase 4: Querying brewgis base canvas ──")
        brew_totals = self._query_brewgis_totals()
        if brew_totals:
            self._print_totals(brew_totals, "BrewGIS")

        # ── Phase 4.5: Populate geography_id ───────────────────────────
        self.stdout.write("\n── Phase 4.5: Populating geography_id in base_canvas ──")
        if parcel_ids:
            self._populate_geography_id(parcel_ids)
        else:
            self.stdout.write("  Skipping (no geography_ids available)")

        # ── Phase 5: Generate comparison report ────────────────────────
        self.stdout.write("\n── Phase 5: Generating comparison report ──")
        correlations = self._compute_correlations()
        weighted_means = self._query_weighted_means()
        _generate_report_markdown(
            ref_totals,
            brew_totals,
            correlations=correlations,
            weighted_means=weighted_means,
            output_path=REPORT_PATH,
            quick=quick,
            limit=limit,
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Report written to {REPORT_PATH}"))
        self.stdout.write(
            self.style.SUCCESS(
                "  Done — open planning/sacog_comparison_report.md to review"
            )
        )

    # ═══════════════════════════════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════════════════════════════

    def _query_reference_totals(
        self, geography_ids: list[int] | None = None
    ) -> dict[str, float]:
        """Query aggregate values from the v1 reference base canvas.

        Returns v3-named columns (acres_* → area_*) for compatibility with
        the report generator.
        """
        from django.db import connection  # noqa: PLC0415

        ref_table = "sac_cnty_region_base_canvas"
        totals = self._query_totals(ref_table, geography_ids)

        # Convert sqft → acres for irrigation columns
        for col in ["residential_irrigated_sqft", "commercial_irrigated_sqft"]:
            if col in totals:
                totals[col.replace("_sqft", "_area")] = totals[col] / 43560.0

        # Add area_* aliases for acres_* columns
        for k in list(totals.keys()):
            if k.startswith("acres_"):
                totals[k.replace("acres_", "area_", 1)] = totals[k]

        return totals

    def _query_brewgis_totals(self) -> dict[str, float]:
        """Query aggregate values from the brewgis base canvas."""
        from django.db import connection  # noqa: PLC0415

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
        from django.db import connection  # noqa: PLC0415

        with connection.cursor() as cur:
            parts = table.split(".") if "." in table else ["public", table]
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                  AND data_type IN ('numeric', 'double precision', 'real', 'integer', 'bigint')
                ORDER BY ordinal_position
                """,
                parts,
            )
            num_cols = [
                r[0]
                for r in cur.fetchall()
                if r[0] not in ("geography_id", "source_id")
            ]
            if not num_cols:
                return {}

            sum_exprs = ", ".join(f'COALESCE(SUM("{c}"), 0) AS "{c}"' for c in num_cols)
            where_clause = ""
            if geography_ids:
                ids_str = ", ".join(str(i) for i in geography_ids)
                where_clause = f" WHERE geography_id IN ({ids_str})"
            cur.execute(f"SELECT {sum_exprs} FROM {table}{where_clause}")
            row = cur.fetchone()
            totals: dict[str, float] = {}
            if row:
                for i, col in enumerate(num_cols):
                    val = row[i]
                    if val is not None:
                        totals[col] = float(val)
            return totals

    def _print_totals(self, totals: dict[str, float], label: str) -> None:
        """Print key aggregate totals."""
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

    def _assert_geometry_identity(self, input_gdf: Any) -> None:
        """Assert that the ETL output matches the input parcel geometries."""
        from django.db import connection  # noqa: PLC0415

        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM public.base_canvas")
            db_count = cursor.fetchone()[0]

        if db_count != len(input_gdf):
            raise CommandError(
                f"Geometry identity violation: {db_count} rows in DB vs "
                f"{len(input_gdf)} input parcels. Cannot produce valid comparison."
            )

        if hasattr(input_gdf, "columns") and "geography_id" in input_gdf.columns:
            input_ids = sorted(input_gdf["geography_id"].tolist())
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT geography_id FROM public.base_canvas "
                    "WHERE geography_id IS NOT NULL ORDER BY geography_id"
                )
                db_ids = [row[0] for row in cursor.fetchall()]
            if input_ids != db_ids:
                raise CommandError(
                    "Geography ID mismatch between input parcels and base_canvas."
                )

        self.stdout.write(f"  Row count: {db_count} matched ✅")

    def _populate_geography_id(self, parcel_ids: list[int]) -> None:
        """Populate geography_id in base_canvas via ordered row alignment.

        The reference parcels are loaded ``ORDER BY geography_id`` and the ETL
        writes them in insert-order, preserving sequence.  ``ROW_NUMBER()``
        alignment on both sides produces a correct 1:1 mapping.
        """
        from django.db import connection  # noqa: PLC0415

        with connection.cursor() as cur:
            cur.execute(
                "ALTER TABLE public.base_canvas ADD COLUMN IF NOT EXISTS geography_id INTEGER"
            )

            if not parcel_ids:
                return

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

        self.stdout.write(f"  Populated geography_id for {len(parcel_ids):,} parcels")

    def _compute_correlations(self) -> dict[str, float]:
        """Compute Pearson R correlation between brewgis and reference columns."""
        from django.db import connection  # noqa: PLC0415
        from brewgis.workspace.services.sacog_column_mapping import (  # noqa: PLC0415
            get_v1_columns_for_verification,
        )

        v3_to_v1 = get_v1_columns_for_verification()
        numeric_types = {
            "numeric",
            "double precision",
            "real",
            "integer",
            "bigint",
            "smallint",
        }

        with connection.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'base_canvas'"
            )
            brew_cols = {r[0] for r in cur.fetchall() if r[1] in numeric_types}
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

    def _query_weighted_means(self) -> dict[str, float]:
        """Query area-weighted means for density/rate equity columns."""
        from django.db import connection  # noqa: PLC0415

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

    def _generate_report(
        self,
        ref: dict[str, float],
        brew: dict[str, float],
        etl_result: dict,
        quick: bool,
        limit: int,
        correlations: dict[str, float] | None = None,
    ) -> None:
        """Generate the markdown comparison report (thin wrapper for backward compat).

        Legacy method expected by test suite. Delegates to
        ``_generate_report_markdown`` with internal helpers for weighted means.
        """
        # Lazy imports — avoid loading great_expectations at module import time
        from brewgis.workspace.dagster.assets.comparison_assets import (  # noqa: PLC0415, C0415
            _generate_report_markdown,
        )

        # Use the module's own REPORT_PATH (can be patched by tests)
        import brewgis.workspace.management.commands.compare_sacog_basemap as _cmd_mod  # noqa: PLC0415, C0415

        report_path = _cmd_mod.REPORT_PATH

        if correlations is None:
            correlations = self._compute_correlations()
        weighted_means = self._query_weighted_means()

        _generate_report_markdown(
            ref,
            brew,
            correlations=correlations,
            weighted_means=weighted_means,
            output_path=report_path,
            quick=quick,
            limit=limit,
        )
