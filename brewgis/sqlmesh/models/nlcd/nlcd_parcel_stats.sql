MODEL (
  name brewgis.nlcd.nlcd_parcel_stats,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);


-- NLCD Parcel Statistics Model
--
-- Computes per-parcel zonal statistics from the NLCD land cover raster.
-- Requires the nlcd_raster_table and nlcd_parcel_source to be populated.
--
-- NOTE: Uses ST_ValueCount as a set-returning function in the FROM clause
-- so its output columns (value, count) are plain table columns, not
-- composite field references. This avoids a SQLMesh query-wrapper bug
-- that corrupts composite type field access like (alias).field.

WITH parcel_tiles AS (
    SELECT
        p.id AS parcel_id,
        ST_Clip(r.rast, 1, p.geometry, TRUE, TRUE) AS clipped
    FROM brewgis.nlcd.parcels_wm p
    JOIN public.nlcd_raster r
        ON ST_Intersects(p.geometry, r.rast::geometry)
    WHERE p.geometry IS NOT NULL
),

tile_value_counts AS (
    SELECT
        t.parcel_id,
        vc.value::integer AS vc_value,
        vc.count::integer AS vc_count
    FROM parcel_tiles t,
    ST_ValueCount(t.clipped, 1) AS vc
),

per_parcel_value_counts AS (
    SELECT
        parcel_id,
        vc_value AS nlcd_class,
        SUM(vc_count) AS total_pixels
    FROM tile_value_counts
    GROUP BY parcel_id, vc_value
),

majority_class AS (
    SELECT DISTINCT ON (parcel_id)
        parcel_id,
        vc_value AS majority_nlcd_class
    FROM tile_value_counts
    ORDER BY parcel_id, vc_count DESC
),

-- Compute impervious fraction as a weighted average of NLCD class
-- impervious values, using pixel counts as weights. This replaces
-- ST_Reclass + ST_SummaryStats with the equivalent computation
-- from ST_ValueCount pixel counts, avoiding composite type access.
impervious_frac AS (
    SELECT
        parcel_id,
        CASE
            WHEN SUM(vc_count) > 0
            THEN SUM(vc_count * CASE vc_value
                WHEN 11 THEN 0.0
                WHEN 12 THEN 0.0
                WHEN 21 THEN 0.10
                WHEN 22 THEN 0.30
                WHEN 23 THEN 0.60
                WHEN 24 THEN 0.85
                WHEN 31 THEN 0.50
                ELSE 0.0
            END) / SUM(vc_count)
            ELSE 0.0
        END AS impervious_fraction
    FROM tile_value_counts
    GROUP BY parcel_id
),

all_parcels AS (
    SELECT id AS parcel_id
    FROM brewgis.nlcd.parcels_wm
    WHERE geometry IS NOT NULL
)

SELECT
    ap.parcel_id,
    CASE m.majority_nlcd_class
        WHEN 11 THEN 'water'
        WHEN 12 THEN 'water'
        WHEN 21 THEN 'urban'
        WHEN 22 THEN 'urban'
        WHEN 23 THEN 'urban'
        WHEN 24 THEN 'urban'
        WHEN 31 THEN 'natural'
        WHEN 41 THEN 'natural'
        WHEN 42 THEN 'natural'
        WHEN 43 THEN 'natural'
        WHEN 51 THEN 'natural'
        WHEN 52 THEN 'natural'
        WHEN 71 THEN 'natural'
        WHEN 72 THEN 'natural'
        WHEN 73 THEN 'natural'
        WHEN 74 THEN 'natural'
        WHEN 81 THEN 'agricultural'
        WHEN 82 THEN 'agricultural'
        WHEN 90 THEN 'wetland'
        WHEN 95 THEN 'wetland'
        ELSE 'unknown'
    END AS land_development_category,
    COALESCE(i.impervious_fraction, 0.0) AS impervious_fraction
FROM all_parcels ap
LEFT JOIN majority_class m ON ap.parcel_id = m.parcel_id
LEFT JOIN impervious_frac i ON ap.parcel_id = i.parcel_id;

-- post_statements
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_nlcd_parcel_stats_parcel_id
  ON brewgis.nlcd.nlcd_parcel_stats (parcel_id)
);
