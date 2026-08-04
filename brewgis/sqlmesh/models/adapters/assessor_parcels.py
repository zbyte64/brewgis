"""Region assessor parcel adapter — Python SQL model (blueprinted).

Presents a uniform APN-level parcel contract (``apn, geometry, centroid,
local_geometry, centroid_local, lot_size_acres, landuse, zone, jurisdiction,
land_development_category``) to the shared enrichment pipeline.

- SACOG: reads external county assessor data (``brewgis.staging.
  sacog_assessor_parcels_raw``) and applies the sub-unit APN consolidation +
  land-use development-category mapping.
- Fresno: no external assessor data — passes through ``@{region}.parcel_shim``
  rows with ``apn = parcel_id`` and all assessor-derived fields NULL (the
  enrichment pipeline falls back to regressor estimates).

The branch is driven by the ``source_table`` blueprint variable (a data
availability concern, not a region check); shared methodology models never
see the difference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sqlglot import exp
from sqlmesh import model
from sqlmesh.core.model.definition import ModelKindName

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
                    5.0  -- 5m buffer ensures non-degenerate polygon for co-linear centroids
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
                    30.0  -- 30m buffer ≈ 100ft radius, ~0.7 acres
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
            (ST_Area(ST_SetSRID(local_geometry, {local_srid}))
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

FRESNO_QUERY = """
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


@model(
    "brewgis.@{region}.assessor_parcels",
    kind={"name": ModelKindName.FULL},
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
        "@IF(@source_table != '', brewgis.staging.sacog_assessor_parcels_raw, brewgis.@{region}.parcel_shim)",
    ],
    post_statements=[
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_parcels_geometry_@snapshot_hash ON @this_model USING GIST (geometry)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_parcels_local_geometry_@snapshot_hash ON @this_model USING GIST (local_geometry)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_parcels_centroid_local_@snapshot_hash ON @this_model USING GIST (centroid_local)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_parcels_centroid_@snapshot_hash ON @this_model USING GIST (centroid)",
        "CREATE INDEX IF NOT EXISTS idx_@{region}_assessor_parcels_apn_@snapshot_hash ON @this_model USING btree (apn)",
        "ANALYZE @this_model",
    ],
    blueprints=[
        {
            "region": "sacog",
            "source_table": "brewgis.staging.sacog_assessor_parcels_raw",
        },
        {"region": "fresno", "source_table": ""},
    ],
    is_sql=True,
)
def execute(evaluator: MacroEvaluator, **kwargs: Any) -> str:
    """Return the region-appropriate adapter SQL (SACOG assessor vs Fresno pass-through).

    The returned string is not macro-rendered again by SQLMesh, so @VAR(...)
    references are resolved here via the evaluator before formatting.
    """
    region = evaluator.blueprint_var("region")
    source_table = evaluator.blueprint_var("source_table", "")
    if source_table:
        return SACOG_QUERY.format(
            source_table=source_table,
            local_srid=evaluator.var("local_srid", 3310),
        )
    return FRESNO_QUERY.format(region=region)
