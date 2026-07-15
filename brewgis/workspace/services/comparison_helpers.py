"""Shared helper functions for SACOG base canvas comparison report generation.

Extracted from the removed Dagster ``comparison_assets`` module for reuse
by the ``compare_sacog_basemap`` management command.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from django.conf import settings
from django.db import connection

from brewgis.workspace.services._db import get_engine
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema

V1_PARCELS = "sac_cnty_region_existing_land_use_parcels"
V1_BASE_CANVAS = "sac_cnty_region_base_canvas"
CACHE_DIR: Path = settings.DATA_DOWNLOAD_CACHE_DIR


def _load_parcels(limit: int, cache_dir: str | None = None) -> gpd.GeoDataFrame:
    """Load parcel geometries from reference table or cache.

    Uses SACOG V1 parcels as a starting point.
    """
    import hashlib

    _etl_schema_hash: str = hashlib.md5(  # noqa: S324
        "".join(sorted(BaseCanvasSchema.COLUMN_NAMES)).encode()
        + BaseCanvasSchema.create_table_sql().encode()
    ).hexdigest()[:8]

    cache_base = Path(cache_dir) if cache_dir else CACHE_DIR
    cache_path = cache_base / f"sacog_parcels_502k_{_etl_schema_hash}.geojson"

    if cache_path.exists():
        gdf = gpd.read_file(str(cache_path))
        if limit > 0 and len(gdf) > limit:
            gdf = gdf.head(limit)
    else:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        sql = f"""
            SELECT *, wkb_geometry AS geometry
            FROM {V1_PARCELS}
            ORDER BY geography_id
            {limit_clause}
        """
        gdf = gpd.GeoDataFrame.from_postgis(sql, get_engine(), geom_col="geometry")
        gdf.to_file(str(cache_path), driver="GeoJSON")

    return gdf


def _query_table_as_dict(table_name: str) -> dict[str, float]:
    """Read a single-row dbt materialized table and return as a dict."""
    with connection.cursor() as cur:
        cur.execute(f"SELECT * FROM {table_name}")
        columns = [desc[0] for desc in cur.description]
        row = cur.fetchone()

    result: dict[str, float] = {}
    if row:
        for col, val in zip(columns, row, strict=False):
            if val is not None:
                try:
                    result[col] = float(val)
                except (ValueError, TypeError):
                    pass
    return result


def _convert_reference_totals(ref: dict[str, float]) -> None:
    """Convert reference column names (acres_* to area_*) and units for comparability."""
    # Rename acres_* to area_*
    acres_columns = [k for k in ref if k.startswith("acres_")]
    for col in acres_columns:
        area_col = col.replace("acres_", "area_", 1)
        if area_col not in ref:
            ref[area_col] = ref[col]

    # Convert sqft to acres for irrigation
    for sqft_col in ["residential_irrigated_sqft", "commercial_irrigated_sqft"]:
        area_col = sqft_col.replace("_sqft", "_area")
        if sqft_col in ref:
            ref[area_col] = ref[sqft_col] / 43560.0


def _generate_report_markdown(
    ref: dict[str, float],
    brew: dict[str, float],
    *,
    correlations: dict[str, float] | None = None,
    weighted_means: dict[str, float] | None = None,
    config: dict | None = None,
    diagnostics: dict | None = None,
    output_path: Path,
    quick: bool,
) -> None:
    """Generate the markdown comparison report.

    Reuses the same column grouping and report structure as the original
    management command, but reads from pre-computed dbt tables instead.

    Args:
        ref: Reference (SACOG v1) totals keyed by column name.
        brew: BrewGIS totals keyed by column name.
        correlations: Optional dict of per-column Pearson correlations.
        weighted_means: Optional dict of weighted mean values (unused in report).
        config: Optional dict of configuration flags used in the run.
        diagnostics: Optional dict of calibration diagnostics (coverage stats).
        output_path: Path to write the report markdown file.
        quick: Whether quick mode was enabled.
        limit: Parcel limit used.
    """
    import time

    lines: list[str] = []

    # Column groups for comparison table (label, v1_col, v3_col)
    # v1_col is for reference, v3_col is for brewgis
    col_groups: list[tuple[str, list[tuple[str, str, str]]]] = [
        (
            "Area (acres)",
            [
                ("Gross Area", "acres_gross", "area_gross_acres"),
                ("Parcel Area", "acres_parcel", "area_parcel_acres"),
                ("Res Parcel Area *", "acres_parcel_res", "area_parcel_res_acres"),
                ("Emp Parcel Area *", "acres_parcel_emp", "area_parcel_emp_acres"),
                (
                    "Mixed Use Area *",
                    "acres_parcel_mixed_use",
                    "area_parcel_mixed_use_acres",
                ),
                ("No Use Area *", "acres_parcel_no_use", "area_parcel_no_use_acres"),
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
                ("Medical Services", "emp_medical_services", "emp_medical_services"),
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
                (
                    "Bldg Restaurant",
                    "bldg_sqft_restaurant",
                    "bldg_area_restaurant",
                ),
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
                (
                    "Bldg Wholesale",
                    "bldg_sqft_wholesale",
                    "bldg_area_wholesale",
                ),
            ],
        ),
        (
            "Intersection Density (per sq mi)",
            [
                (
                    "Intersection Density",
                    "intersection_density_sqmi",
                    "intersection_density",
                ),
            ],
        ),
        (
            "Irrigation (acres)",
            [
                (
                    "Res Irrigated",
                    "residential_irrigated_area",
                    "residential_irrigated_area",
                ),
                (
                    "Com Irrigated",
                    "commercial_irrigated_area",
                    "commercial_irrigated_area",
                ),
            ],
        ),
    ]

    lines.append("# SACOG Base Canvas Comparison Report")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("**Region:** Sacramento County, CA (SACOG)")
    lines.append(f"**Reference:** `{V1_BASE_CANVAS}` (2015 vintage, 2008-2012 data)")
    lines.append(f"**Quick mode:** {quick}")
    total_parcels = "?"
    if diagnostics:
        dp = diagnostics.get("dasymetric", {})
        if dp.get("total_parcels", 0):
            total_parcels = f"{dp['total_parcels']:,}"
    lines.append(f"**Parcel limit:** all ({total_parcels})")
    lines.append("")

    # Configuration section
    if config:
        lines.append("## Configuration")
        lines.append("")
        lines.append("| Flag | Value |")
        lines.append("|------|-------|")
        for key, value in sorted(config.items()):
            val_str = str(value).lower() if isinstance(value, bool) else str(value)
            lines.append(f"| `--{key}` | {val_str} |")
        lines.append("")

    # Calibration Diagnostics section
    if diagnostics:
        dasym = diagnostics.get("dasymetric", {})
        assessor = diagnostics.get("assessor", {})
        lines.append("## Calibration Diagnostics")
        lines.append("")
        lines.append("### Assessor Data Coverage")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        total_parcels = dasym.get("total_parcels", 0)
        assessor_parcels = dasym.get("assessor_parcels", 0)
        pct = (assessor_parcels / total_parcels * 100) if total_parcels > 0 else 0
        lines.append(f"| Total parcels | {total_parcels:,} |")
        lines.append(f"| Parcels with du_subtype | {assessor_parcels:,} ({pct:.1f}%) |")
        lines.append(
            f"| Parcels with pop_dasym_weight | {dasym.get('pop_weight_parcels', 0):,} |"
        )
        if "du_subtype_breakdown" in dasym:
            lines.append("")
            lines.append("**DU Sub-type Breakdown:**")
            lines.append("")
            lines.append("| Sub-type | Count |")
            lines.append("|----------|-------|")
            for st, count in sorted(dasym.get("du_subtype_breakdown", {}).items()):
                label = st if st else "NULL (no assessor data)"
                lines.append(f"| {label} | {count:,} |")
        lc = assessor.get("land_development_category", {})
        if lc:
            lines.append("")
            lines.append(
                "**Land Development Category Distribution (from assessor use codes):**"
            )
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|----------|-------|")
            for cat, count in sorted(lc.items()):
                lines.append(f"| {cat} | {count:,} |")
        emp = diagnostics.get("employment", {})
        if emp:
            lines.append("")
            lines.append("### Employment Pipeline")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(
                f"| WAC blocks with geometry | {emp.get('wac_blocks_with_geom', 0):,} |"
            )
            lines.append(f"| Total WAC blocks | {emp.get('total_wac_blocks', 0):,} |")

        rs = diagnostics.get("road_surface", {})
        # Road Surface Diagnostics (Overture Transportation)
        if config and config.get("overture-roads"):
            lines.append("")
            lines.append("### Road Surface Diagnostics (Overture Transportation)")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            if rs.get("error"):
                lines.append(f"| Error | {rs['error']} |")
            seg = rs.get("segment_count", 0)
            paved = rs.get("paved_segments", 0)
            unpaved = rs.get("unpaved_segments", 0)
            paved_pct = paved / seg * 100 if seg > 0 else 0
            unpaved_pct = unpaved / seg * 100 if seg > 0 else 0
            lines.append(f"| Road segments | {seg:,} |")
            lines.append(f"| Paved segments | {paved:,} ({paved_pct:.1f}%) |")
            lines.append(f"| Unpaved segments | {unpaved:,} ({unpaved_pct:.1f}%) |")
            parcels_with = rs.get("parcels_with_roads", 0)
            total_parcels_rs = rs.get("total_parcels", 0)
            parcel_pct = (
                parcels_with / total_parcels_rs * 100 if total_parcels_rs > 0 else 0
            )
            lines.append(
                f"| Parcels intersecting roads | {parcels_with:,} ({parcel_pct:.1f}%) |"
            )
            lines.append(
                f"| Total paved road area | {rs.get('total_road_paved_area', 0):,.1f} acres |"
            )
            lines.append(
                f"| Total unpaved road area | {rs.get('total_road_unpaved_area', 0):,.1f} acres |"
            )
            lines.append(
                f"| Avg road impervious fraction | "
                f"{rs.get('avg_road_impervious_fraction', 0):.4f} |"
            )
            # Surface class breakdown (compact)
            scb = rs.get("surface_class_breakdown", {})
            if scb:
                class_str = ", ".join(f"{k}: {v:,}" for k, v in scb.items())
                lines.append(f"| Surface class breakdown | {class_str} |")
            # Error details
            error_keys = [k for k in rs if k.startswith("error_") and rs[k]]
            for ek in sorted(error_keys):
                lines.append(f"| {ek} | {rs[ek]} |")

        # ResNet Feature Coverage
        rn = diagnostics.get("resnet", {})
        lines.append("")
        lines.append("### ResNet Feature Coverage")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        total_rows = rn.get("total_rows", 0)
        unique_apns = rn.get("unique_apns", 0)
        cmp_with = rn.get("comparison_parcels_with_features", 0)
        cmp_total = rn.get("comparison_parcels_total", 0)
        pct = cmp_with / cmp_total * 100 if cmp_total > 0 else 0
        lines.append(f"| ResNet feature rows | {total_rows:,} |")
        lines.append(f"| Unique APNs with features | {unique_apns:,} |")
        lines.append(
            f"| Comparison parcels with ResNet features | {cmp_with:,} ({pct:.2f}%) |"
        )
        lines.append(f"| Comparison parcels total | {cmp_total:,} |")
        lon_min = rn.get("min_lon", 0.0)
        lon_max = rn.get("max_lon", 0.0)
        lat_min = rn.get("min_lat", 0.0)
        lat_max = rn.get("max_lat", 0.0)
        if lon_min or lon_max or lat_min or lat_max:
            lines.append(f"| Spatial extent (lon) | [{lon_min:.4f}, {lon_max:.4f}] |")
            lines.append(f"| Spatial extent (lat) | [{lat_min:.4f}, {lat_max:.4f}] |")

        lines.append("")
    lines.append("")

    # Summary comparison table
    lines.append("## 1. Aggregate Comparison")
    lines.append("")
    lines.append(
        "| Column | Reference (v1) | BrewGIS | Diff | % Diff | Corr (R) | Status |"
    )
    lines.append("|--------|--------:|------:|-----:|------:|---------:|:-------|")

    matched_count = 0
    for group_label, col_list in col_groups:
        lines.append(f"\n### {group_label}\n")

        for label, v1_col, v3_col in col_list:
            ref_val = ref.get(v1_col)
            brew_val = brew.get(v3_col)

            if ref_val is None and brew_val is None:
                continue

            ref_str = f"{ref_val:>14,.1f}" if ref_val is not None else f"{'N/A':>14}"
            brew_str = f"{brew_val:>14,.1f}" if brew_val is not None else f"{'N/A':>14}"

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

            # Strip _acres suffix for area columns where correlation keys use bare names
            _corr_key = v3_col.removesuffix("_acres")
            corr_val = correlations.get(_corr_key) if correlations else None
            corr_str = f"{corr_val:.3f}" if corr_val is not None else "N/A"

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
                f"| {label:25s} | {ref_str} | {brew_str} | {diff_str} | {pct_str} "
                f"| {corr_str:>9s} | {status:>7s} |"
            )

    lines.append(f"\n**Columns matched:** {matched_count}")

    # Correlation quality summary
    if correlations:
        corr_vals = [v for v in correlations.values() if v is not None]
        if corr_vals:
            good = sum(1 for v in corr_vals if v >= 0.70)
            ok = sum(1 for v in corr_vals if 0.50 <= v < 0.70)
            warn = sum(1 for v in corr_vals if 0.30 <= v < 0.50)
            poor = sum(1 for v in corr_vals if 0.10 <= v < 0.30)
            fail = sum(1 for v in corr_vals if v < 0.10)
            lines.append(
                f"\n**Correlation quality:** {good} GOOD, {ok} OK, {warn} WARN, "
                f"{poor} POOR, {fail} FAIL (based on {len(corr_vals)} columns)"
            )

    # Data sources
    lines.append("\n## 2. Data Sources Used")
    lines.append("")
    lines.append("| Data Domain | Reference (v1) | BrewGIS |")
    lines.append("|-------------|-----------------|---------|")
    lines.append(
        "| Parcel geometries | SACOG Assessor | Same (extracted from reference) |"
    )
    _acs_year = str(config.get("acs-year", "?")) if config else "?"
    lines.append(
        "| Demographics | SACOG 2008 + ACS blockgroup rates "
        f"| Census ACS {_acs_year} blockgroup area-weighted |"
    )
    lines.append(
        "| Employment | SACOG 2008 + LEHD disaggregation "
        "| LEHD LODES WAC block area-weighted |"
    )
    lines.append(
        "| Dwelling units | SACOG parcel DU + TAZ controls "
        "| Inferred from ACS HH/occupancy |"
    )
    _nlcd_year = str(config.get("nlcd-year", "?")) if config else "?"
    lines.append(
        "| Land use | SACOG use code crosswalk | "
        + (f"NLCD {_nlcd_year}" if not quick else "Default (Null source)")
        + " |"
    )
    lines.append(
        "| Intersection density | CA walkable intersection points | "
        + ("OSM road network" if not quick else "Default (12.5)")
        + " |"
    )
    lines.append(
        "| Building area | Derived from DU/emp + sqft factors "
        "| Same (default 1200sqft/DU, 300sqft/emp) |"
    )
    lines.append(
        "| Irrigation | Parcel area-based fractions | "
        + ("NLCD impervious" if not quick else "Default (25%/3.5%)")
        + " |"
    )
    if config and config.get("overture-roads"):
        lines.append(
            "| Road surface | N/A (SACOG v1 has no road surface data) "
            "| Overture Transportation road segments |"
        )

    lines.append("")
    lines.append(
        "_* Res/Emp/Mixed/No-use parcel area allocated via "
        "dasymetric weighting (assessor use codes + ACS)._\n"
    )

    # Authoritative Building Intersection Diagnostics
    if diagnostics and diagnostics.get("authoritative", {}).get("total_parcels", 0) > 0:
        auth = diagnostics["authoritative"]
        total = auth["total_parcels"]

        lines.append("\n## 4. Authoritative Building Intersection Diagnostics")
        lines.append("")

        # Coverage Summary
        lines.append("### Coverage Summary")
        lines.append("")
        lines.append("| Category | Count | % | Mean Parcel Size (acres) |")
        lines.append("|----------|------:|---:|-------------------------:|")

        def _pct(val: int) -> str:
            return f"{(val / total * 100):.1f}" if total > 0 else "0.0"

        overture_count = auth.get("overture_residential_match", 0)
        assessor_count = auth.get("assessor_sales_only", 0)
        footprint_imputed_count = auth.get("footprint_imputed", 0)
        none_count = auth.get("no_authoritative_data", 0)

        def _acres_str(key: str) -> str:
            val = auth.get(f"mean_acres_{key}", 0.0) or 0.0
            return f"{val:>7.1f}"

        lines.append(
            f"| Overture residential match | {overture_count:>9,} | {_pct(overture_count):>5}% | "
            f"{_acres_str('overture')} |"
        )
        lines.append(
            f"| Assessor sales only | {assessor_count:>9,} | {_pct(assessor_count):>5}% | "
            f"{_acres_str('assessor_only')} |"
        )
        lines.append(
            f"| Footprint imputed | {footprint_imputed_count:>9,} | {_pct(footprint_imputed_count):>5}% | "
            f"{_acres_str('footprint_imputed')} |"
        )
        lines.append(
            f"| No authoritative data (NULL) | {none_count:>9,} | {_pct(none_count):>5}% | "
            f"{_acres_str('no_data')} |"
        )
        lines.append("")

        # Building Count Distribution
        lines.append("### Building Count Distribution")
        lines.append("")
        lines.append("| Buildings per Parcel | Count | % |")
        lines.append("|---------------------|------:|---:|")
        for bucket in ["0", "1", "2-5", "6-10", "11-50", "50+"]:
            cnt = auth.get("building_count_breakdown", {}).get(bucket, 0)
            lines.append(f"| {bucket:>20s} | {cnt:>8,} | {_pct(cnt):>5}% |")
        lines.append("")

        # Straddling Buildings
        lines.append("### Straddling Buildings")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(
            f"| Buildings intersecting multiple parcels | "
            f"{auth.get('straddling_buildings', 0):>9,} |"
        )
        lines.append(
            f"| Parcels with straddling buildings | "
            f"{auth.get('parcels_with_straddling', 0):>9,} |"
        )
        lines.append("")

        # Coverage by Land Development Category
        cov = auth.get("coverage_by_category", {})
        if cov:
            lines.append("### Coverage by Land Development Category")
            lines.append("")
            lines.append(
                "| Category | Total Parcels | With Overture | % Covered |"
                " Mean Sqft/Parcel |"
            )
            lines.append(
                "|----------|-------------:|-------------:|----------:|-----------------:|"
            )
            for cat in [
                "urban",
                "industrial",
                "agricultural",
                "undeveloped",
                "unknown",
            ]:
                if cat in cov:
                    stats = cov[cat]
                    covered_pct = (
                        (stats["covered"] / stats["total"] * 100)
                        if stats["total"] > 0
                        else 0.0
                    )
                    lines.append(
                        f"| {cat:24s} | {stats['total']:>9,} | {stats['covered']:>9,} |"
                        f" {covered_pct:>7.1f}% | {stats['mean_sqft']:>9,.0f} |"
                    )
            lines.append("")

    # Per-column detailed correlation
    if correlations:
        lines.append("\n## 3. Correlation Details")
        lines.append("")

        # Sort by abs(r) descending
        sorted_corrs = sorted(
            [(k, v) for k, v in correlations.items() if v is not None],
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )

        lines.append("| Column | Correlation (R) | Quality |")
        lines.append("|--------|----------------:|:--------|")

        for col, val in sorted_corrs:
            if val >= 0.70:
                qual = "GOOD"
            elif val >= 0.50:
                qual = "OK"
            elif val >= 0.30:
                qual = "WARN"
            elif val >= 0.10:
                qual = "POOR"
            else:
                qual = "FAIL"
            lines.append(f"| {col:40s} | {val:15.3f} | {qual:>7s} |")

        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
