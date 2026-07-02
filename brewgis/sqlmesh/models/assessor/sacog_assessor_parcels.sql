MODEL (
  name brewgis.assessor.sacog_assessor_parcels,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_sacog_assessor_parcels_row_count
  )
);

-- SACOG Assessor Parcels — parcel geometries from Sacramento County Assessor,
-- deduplicated by apn, with sub-unit APNs (condos/PUDs/mobile home pads with
-- lotsize=0) consolidated into development-level parcels.
--
-- Reads from public.sacog_assessor_parcels_raw (populated by the assessor dlt
-- pipeline from PARCELS/MapServer/8).
--
-- Sub-unit APNs (lotsize=0 or NULL) represent individual tax parcels within
-- PUDs, mobile home parks, condos, and townhome complexes. Each has lotsize=0
-- and a tiny geometry (< $10^{-13}$ acres). The consolidation groups them by
-- APN prefix-8 (property-level) and emits one synthetic row per development
-- with the convex hull of the sub-unit centroids as the parcel geometry and
-- area-derived lot size.
--
-- ArcGIS PARCELS/MapServer/8 may return multiple features per APN (multi-part
-- parcels, land-use splits, etc.). Normal parcels are deduplicated by taking
-- the row with the largest lotsize per apn.

WITH
-- Identify sub-unit parcels (zero or null lotsize — individual condo/PUD pads)
sub_unit_parcels AS (
    SELECT *
    FROM public.sacog_assessor_parcels_raw
    WHERE (lotsize IS NULL OR lotsize::double precision <= 0)
      AND geometry IS NOT NULL  -- skip rows without spatial data
) ,

-- Consolidate sub-unit parcels into development-level rows by APN prefix-8.
-- For groups with >=3 sub-units, the geometry is the convex hull of their
-- projected centroids (capturing the development's spatial extent).
-- For smaller groups (1-2 sub-units), buffer 30m around the centroid cluster
-- to produce a non-degenerate polygon.
consolidated_subunits AS (
    SELECT
        LEFT(apn, 8) || '0000' AS apn,
        CASE
            WHEN COUNT(*) >= 3
            THEN ST_Buffer(
                ST_ConvexHull(
                    ST_Collect(ST_Centroid(ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310))))
                ),
                5.0  -- 5m buffer ensures non-degenerate polygon for co-linear centroids
            )
            ELSE ST_Buffer(
                ST_Centroid(
                    ST_Collect(ST_Centroid(ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310))))
                ),
                30.0  -- 30m buffer ≈ 100ft radius, ~0.7 acres
            )
        END AS local_geometry,  -- SRID @VAR('local_srid', 3310)
        mode() WITHIN GROUP (ORDER BY landuse) AS landuse,
        mode() WITHIN GROUP (ORDER BY zone) AS zone,
        mode() WITHIN GROUP (ORDER BY jurisdiction) AS jurisdiction,
        COUNT(*) AS subunit_count
    FROM sub_unit_parcels
    GROUP BY LEFT(apn, 8)
),

-- Deduped normal parcels (positive lotsize, with landuse or blank).
-- Each APN may appear multiple times in the raw table; we take the row with
-- the largest lotsize to get the canonical geometry.
deduped AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY apn
            ORDER BY lotsize::double precision DESC NULLS LAST
        ) AS rn
    FROM public.sacog_assessor_parcels_raw
    WHERE lotsize IS NOT NULL AND lotsize::double precision > 0
),

-- Combined: consolidated sub-unit rows + deduped normal parcels
combined AS (
    SELECT
        apn,
        ST_Transform(local_geometry, 4326) AS geometry,
        ST_Centroid(ST_Transform(local_geometry, 4326)) AS centroid,
        local_geometry,
        ST_Centroid(local_geometry) AS centroid_local,
        (ST_Area(local_geometry) / 4046.8564224)::double precision AS lot_size_acres,
        landuse,
        zone,
        jurisdiction
    FROM consolidated_subunits

    UNION ALL

    SELECT
        apn,
        ST_MakeValid(geometry) AS geometry,
        ST_Centroid(ST_MakeValid(geometry)) AS centroid,
        ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310)) AS local_geometry,
        ST_Centroid(ST_Transform(ST_MakeValid(geometry), @VAR('local_srid', 3310))) AS centroid_local,
        (lotsize::double precision / 43560.0)::double precision AS lot_size_acres,
        landuse,
        zone,
        jurisdiction
    FROM deduped
    WHERE rn = 1
)

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
FROM combined c
LEFT JOIN brewgis.seeds.assessor_use_codes auc
    ON LEFT(COALESCE(c.landuse::text, ''), 2) = auc.use_code::text;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_local_geometry_@snapshot_hash
  ON @this_model USING GIST (local_geometry);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_centroid_local_@snapshot_hash
  ON @this_model USING GIST (centroid_local);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_centroid_@snapshot_hash
  ON @this_model USING GIST (centroid);
  CREATE INDEX IF NOT EXISTS idx_sacog_assessor_parcels_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  ANALYZE @this_model;
