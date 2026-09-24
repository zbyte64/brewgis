"""Region assessor parcel adapter — Python SQL model (blueprinted).

Presents a uniform APN-level parcel contract (``apn, geometry, centroid,
local_geometry, centroid_local, lot_size_acres, landuse, zone, jurisdiction,
land_development_category``) to the shared enrichment pipeline.

- SACOG: reads external county assessor data (``brewgis.sacog.
  assessor_parcels_raw``) and applies the sub-unit APN consolidation +
  land-use development-category mapping.
- Fresno: reads the county assessor roll (``brewgis.fresno.
  assessor_parcels_raw``, the FC_PARCEL_SELECT MapServer), collapses its
  situs-address feature grain to one row per APN, and maps the county's
  ``use_high_best`` highest-and-best-use code to ``land_development_category``
  (``use_primary`` is not a usable signal — its A## codes are apartment/condo
  pads and apartment master parcels). ``zone``/``jurisdiction`` stay NULL — no
  consumer needs a public per-parcel zoning join.

The branch is driven by the region (Fresno's roll codes are a different code
system from SACOG's); a region whose ``source_table`` blueprint variable is
empty falls back to the ``@{region}.parcel_shim`` pass-through. Shared
methodology models never see the difference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

from brewgis.sqlmesh.macros.geometry import metres_per_unit
from brewgis.sqlmesh.macros.geometry import require_local_srid
from brewgis.sqlmesh.macros.region_blueprints import REGIONS

if TYPE_CHECKING:
    from sqlmesh.core.macros import MacroEvaluator

SACOG_QUERY = """
SELECT
    c.apn,
    c.geometry,
    c.centroid,
    c.local_geometry,
    c.centroid_local,
    c.lot_size_acres,
    c.landuse,
    c.zone,
    c.jurisdiction,
    COALESCE(
        auc.category,
        CASE
            WHEN c.landuse IS NULL OR c.landuse = '' THEN 'undeveloped'
            WHEN LEFT(c.landuse::text, 1) = 'A' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'B' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'C' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'D' THEN 'undeveloped'
            WHEN LEFT(c.landuse::text, 1) = 'E' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'F' THEN 'agricultural'
            WHEN LEFT(c.landuse::text, 1) = 'G' THEN 'undeveloped'
            WHEN LEFT(c.landuse::text, 1) = 'H' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'I' THEN 'industrial'
            WHEN LEFT(c.landuse::text, 2) IN ('MP','MR','MW','MD','MF','MG','ML') THEN 'undeveloped'
            WHEN LEFT(c.landuse::text, 1) = 'M' THEN 'urban'
            WHEN LEFT(c.landuse::text, 1) = 'W' THEN 'undeveloped'
            ELSE 'undeveloped'
        END,
        'urban'
    ) AS land_development_category
FROM (
    WITH
    -- Identify sub-unit parcels (zero or null lotsize — individual condo/PUD pads)
    sub_unit_parcels AS (
        SELECT *
        FROM {source_table}
        WHERE (lotsize IS NULL OR lotsize::double precision <= 0)
          AND wgs84_geometry IS NOT NULL  -- skip rows without spatial data
    ) ,

    -- Consolidate sub-unit APNs into development-level rows by APN prefix-8.
    consolidated_subunits AS (
        SELECT
            LEFT(apn, 8) || '0000' AS apn,
            CASE
                WHEN COUNT(*) >= 3
                ST_Buffer(
                    ST_ConvexHull(
                        ST_Collect(
                            ST_Centroid(
                                ST_Transform(
                                    ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326),
                                    {local_srid}
                                )
                            )
                        )
                    ),
                    {buffer_5m}  -- 5 m buffer ensures non-degenerate polygon for co-linear centroids
                )
                ELSE ST_Buffer(
                    ST_Centroid(
                        ST_Collect(
                            ST_Centroid(
                                ST_Transform(
                                    ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326),
                                    {local_srid}
                                )
                            )
                        )
                    ),
                    {buffer_30m}  -- 30 m buffer ≈ 100ft radius, ~0.7 acres
                )
            END AS local_geometry,  -- SRID {local_srid}
            mode() WITHIN GROUP (ORDER BY landuse) AS landuse,
            mode() WITHIN GROUP (ORDER BY zone) AS zone,
            mode() WITHIN GROUP (ORDER BY jurisdiction) AS jurisdiction,
            COUNT(*) AS subunit_count
        FROM sub_unit_parcels
        GROUP BY LEFT(apn, 8)
    ),

    -- Deduped normal parcels (positive lotsize). Each APN may appear multiple
    -- times in the raw table; take the row with the largest lotsize.
    deduped AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY apn
                ORDER BY lotsize::double precision DESC NULLS LAST
            ) AS rn
        FROM {source_table}
        WHERE lotsize IS NOT NULL AND lotsize::double precision > 0
    ),

    combined AS (
        SELECT
            apn,
            ST_Transform(
                ST_SetSRID(local_geometry, {local_srid}),
                4326
            ) AS geometry,
            ST_Centroid(
                ST_Transform(
                    ST_SetSRID(local_geometry, {local_srid}),
                    4326
                )
            ) AS centroid,
            ST_SetSRID(local_geometry, {local_srid}) AS local_geometry,
            ST_Centroid(
                ST_SetSRID(local_geometry, {local_srid})
            ) AS centroid_local,
            (ST_Area(ST_SetSRID(local_geometry, {local_srid})) * {sqm_per_square_unit}
                / 4046.8564224)::double precision AS lot_size_acres,
            landuse,
            zone,
            jurisdiction
        FROM consolidated_subunits

        UNION ALL

        SELECT
            apn,
            ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326) AS geometry,
            ST_Centroid(
                ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326)
            ) AS centroid,
            ST_Transform(
                ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326),
                {local_srid}
            ) AS local_geometry,
            ST_Centroid(
                ST_Transform(
                    ST_SetSRID(ST_MakeValid(wgs84_geometry), 4326),
                    {local_srid}
                )
            ) AS centroid_local,
            (lotsize::double precision / 43560.0)::double precision AS lot_size_acres,
            landuse,
            zone,
            jurisdiction
        FROM deduped
        WHERE rn = 1
    )
    SELECT * FROM combined
) c
LEFT JOIN brewgis.seeds.assessor_use_codes auc
    ON LEFT(COALESCE(c.landuse::text, ''), 2) = auc.use_code::text;
"""

PASSTHROUGH_QUERY = """
SELECT
    ps.parcel_id AS apn,
    ps.geometry,
    ST_Centroid(ps.geometry) AS centroid,
    ps.local_geometry,
    ST_Centroid(ps.local_geometry) AS centroid_local,
    COALESCE(ps.acres, 0)::double precision AS lot_size_acres,
    NULL::text AS landuse,
    NULL::text AS zone,
    NULL::text AS jurisdiction,
    'urban'::text AS land_development_category
FROM brewgis.{region}.parcel_shim ps;
"""

# Fresno assessor roll: one row per APN. The roll is sourced at situs-address
# feature grain (a parcel with several addresses appears more than once), so
# collapse by APN with ST_Union (parcel extent = union of its features) and
# mode() for the use code — the same consolidation pattern SACOG's sub-unit
# pass uses. The DuckDB→PostGIS FDW drops SRID metadata, so the geometry
# arrives as SRID 0 and is ST_SetSRID-tagged 4326 before the union (the
# duckdb-geometry linter rule requires the raw column wrapped innermost).
#
# land_development_category comes from the county's own USE_HIGH_BEST
# highest-and-best-use code, validated against the in-bbox roll (229,054
# APNs): hb 'A' is 2,726 APNs at 24 acres mean (89% >= 5 acres, land-dominant
# value) and hb 'O' is 1,759 APNs at 44 acres mean carrying the same crop-code
# families (ALM, VIR, FIE, ORA, TRX, TVX, VIW, ...), so both are agricultural.
# The settlement families stay urban: 'S' single family (0.4 acres mean), 'P'
# (0.0), 'C' commercial (1.3), 'M' multi-family (0.6), 'I' industrial (2.6).
# The 2-acre floor drops the ~200 rows the county mislabels (e.g. 103 hb-'O'
# S01 single-family parcels at 1.4 acres median).
#
# USE_PRIMARY is NOT usable as the signal on its own: A01-A16 are 0.02-0.57
# acre apartment/condo pads and A99 is an apartment *master* parcel (one APN
# carries 6,963 situs addresses), and a hand-built crop-code list picks up
# non-farm codes alongside the real ones (CHU, GAR and WAH are all under 1
# acre median). Blank/XXX/000 codes have no assessable use → undeveloped.
FRESNO_ASSESSOR_QUERY = """
WITH collapsed AS (
    SELECT
        apn,
        ST_Union(ST_MakeValid(ST_SetSRID(geometry, 4326))) AS wgs84_geometry,
        mode() WITHIN GROUP (ORDER BY use_primary) AS use_primary,
        mode() WITHIN GROUP (ORDER BY use_high_best) AS use_high_best,
        MAX(total_assessed_value) AS total_assessed_value,
        MAX(lot_size_acres) AS lot_size_acres
    FROM {source_table}
    WHERE apn IS NOT NULL AND trim(apn) <> ''
    GROUP BY apn
),
resolved AS (
    SELECT
        apn,
        wgs84_geometry,
        use_primary,
        use_high_best,
        -- A non-positive LOT_AREA is a missing measurement, not a zero-acre
        -- parcel (SACOG's adapter reads lotsize <= 0 the same way): 1,769 roll
        -- rows carry LOT_AREA = 0 and all of them have a positive geometric
        -- area. Left as 0 they zero out the lot-size employment fallback in
        -- parcel_dasymetric_weights and fail assert_emp_dasym_weight_fallback.
        COALESCE(
            CASE WHEN lot_size_acres > 0 THEN lot_size_acres END,
            (ST_Area(ST_Transform(wgs84_geometry, {local_srid})) * {sqm_per_square_unit}
                / 4046.8564224)::double precision
        ) AS lot_size_acres
    FROM collapsed
)
SELECT
    apn,
    wgs84_geometry AS geometry,
    ST_Centroid(wgs84_geometry) AS centroid,
    ST_Transform(wgs84_geometry, {local_srid}) AS local_geometry,
    ST_Centroid(ST_Transform(wgs84_geometry, {local_srid})) AS centroid_local,
    lot_size_acres,
    use_primary AS landuse,
    NULL::text AS zone,
    NULL::text AS jurisdiction,
    CASE
        WHEN use_primary IS NULL OR trim(use_primary) = '' OR use_primary IN ('XXX','000')
            THEN 'undeveloped'
        WHEN use_high_best IN ('A','O') AND lot_size_acres >= 2
            THEN 'agricultural'
        ELSE 'urban'
    END AS land_development_category
FROM resolved;
"""


_SOURCE_TABLE = {
    "sacog": "brewgis.sacog.assessor_parcels_raw",
    "fresno": "brewgis.fresno.assessor_parcels_raw",
}


@model(
    "brewgis.@{region}.assessor_parcels",
    kind={"name": ModelKindName.FULL},
    description="Uniform APN-level assessor parcel contract, sourced from each region's county assessor roll.",
    column_descriptions={
        "apn": "Assessor parcel number (APN) of the parcel; unique per row.",
        "geometry": "Parcel boundary in WGS84 (EPSG:4326), repaired with ST_MakeValid.",
        "centroid": "Centroid of the WGS84 parcel boundary (EPSG:4326).",
        "local_geometry": "Parcel boundary in the region local projected SRID (local_srid).",
        "centroid_local": "Centroid of the parcel in the region local_srid, used for radius joins.",
        "lot_size_acres": "Parcel lot size (acres) from the assessor roll; parcel_shim acres in the pass-through case.",
        "landuse": "Assessor land use code of the parcel (SACOG landuse, Fresno use_primary).",
        "zone": "Assessor zoning code of the parcel; NULL where the region has no per-parcel zoning source.",
        "jurisdiction": "Jurisdiction the parcel lies in; NULL where the region has no per-parcel zoning source.",
        "land_development_category": "Development category of the parcel from the assessor use code.",
    },
    columns={
        "apn": "text",
        "geometry": "geometry",
        "centroid": "geometry",
        "local_geometry": "geometry",
        "centroid_local": "geometry",
        "lot_size_acres": "double",
        "landuse": "text",
        "zone": "text",
        "jurisdiction": "text",
        "land_development_category": "text",
    },
    audits=[
        ("not_null", {"columns": [exp.to_column("apn")]}),
        ("unique_values", {"columns": [exp.to_column("apn")]}),
    ],
    depends_on=[
        "@IF(@source_table != '', brewgis.@{region}.assessor_parcels_raw, brewgis.@{region}.parcel_shim)",
    ],
    post_statements=[
        "CREATE INDEX IF NOT EXISTS "
        "@snapshot_hash('idx_assessor_parcels_geometry_') "
        "ON @this_model USING GIST (geometry)",
        "CREATE INDEX IF NOT EXISTS "
        "@snapshot_hash('idx_assessor_parcels_local_geometry_') "
        "ON @this_model USING GIST (local_geometry)",
        "CREATE INDEX IF NOT EXISTS "
        "@snapshot_hash('idx_assessor_parcels_centroid_local_') "
        "ON @this_model USING GIST (centroid_local)",
        "CREATE INDEX IF NOT EXISTS "
        "@snapshot_hash('idx_assessor_parcels_centroid_') "
        "ON @this_model USING GIST (centroid)",
        "CREATE INDEX IF NOT EXISTS "
        "@snapshot_hash('idx_assessor_parcels_apn_') "
        "ON @this_model USING btree (apn)",
        "ANALYZE @this_model",
    ],
    blueprints=[{"region": r, "source_table": _SOURCE_TABLE[r]} for r in REGIONS],
    is_sql=True,
)
def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the region-appropriate adapter SQL (SACOG or Fresno assessor roll).

    The returned string is not macro-rendered again by SQLMesh, so @VAR(...)
    references are resolved here via the evaluator before formatting — and so
    are the local CRS's unit conversions (``local_srid``'s linear unit is
    whatever that CRS defines; areas and buffer radii are scaled by it).
    """
    region = evaluator.blueprint_var("region")
    source_table = evaluator.blueprint_var("source_table", "")
    if not source_table:
        return PASSTHROUGH_QUERY.format(region=region)
    local_srid = require_local_srid(evaluator)
    unit_m = metres_per_unit(local_srid)
    if region == "fresno":
        return FRESNO_ASSESSOR_QUERY.format(
            source_table=source_table,
            local_srid=local_srid,
            sqm_per_square_unit=repr(unit_m**2),
        )
    return SACOG_QUERY.format(
        source_table=source_table,
        local_srid=local_srid,
        sqm_per_square_unit=repr(unit_m**2),
        buffer_5m=repr(5.0 / unit_m),
        buffer_30m=repr(30.0 / unit_m),
    )
