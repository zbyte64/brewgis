MODEL (
  name brewgis.nlcd.nlcd_tree_canopy_parcel_stats,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);


-- NLCD Tree Canopy Parcel Statistics Model
--
-- Computes per-parcel mean tree canopy fraction from the NLCD USFS
-- Tree Canopy Cover raster. The tree canopy product contains continuous
-- 0-100% pixel values at 30m resolution.
--
-- Uses ST_Clip + ST_SummaryStats (mean) since the data is continuous,
-- not categorical like the NLCD land cover classes.

WITH raster_extent AS (
    SELECT ST_SetSRID(ST_Extent(rast::geometry), 5070) AS extent
    FROM public.nlcd_tree_canopy_raster
),

parcels_5070 AS (
    SELECT
        p.id AS parcel_id,
        ST_Transform(p.geometry, 5070) AS geometry_5070
    FROM brewgis.nlcd.parcels_wm p
    JOIN raster_extent re ON ST_Intersects(p.geometry, re.extent)
    WHERE p.geometry IS NOT NULL
),

parcel_tiles AS (
    SELECT
        p.parcel_id,
        ST_Clip(r.rast, 1, p.geometry_5070, TRUE, TRUE) AS clipped
    FROM parcels_5070 p
    JOIN public.nlcd_tree_canopy_raster r
        ON ST_Intersects(p.geometry_5070, r.rast::geometry)
),

tile_stats AS (
    SELECT
        t.parcel_id,
        (ST_SummaryStats(t.clipped, 1, FALSE)).mean AS canopy_mean
    FROM parcel_tiles t
),

-- A parcel may intersect multiple raster tiles; average per-tile means
-- to produce one row per parcel.
per_parcel_stats AS (
    SELECT
        parcel_id,
        CASE
            WHEN AVG(canopy_mean) IS NOT NULL
            THEN GREATEST(0.0, LEAST(100.0, AVG(canopy_mean)))
        END AS tree_canopy_fraction
    FROM tile_stats
    GROUP BY parcel_id
),

all_parcels AS (
    SELECT id AS parcel_id
    FROM brewgis.nlcd.parcels_wm
    WHERE geometry IS NOT NULL
)

SELECT
    ap.parcel_id,
    s.tree_canopy_fraction
FROM all_parcels ap
LEFT JOIN per_parcel_stats s ON ap.parcel_id = s.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_nlcd_tree_canopy_parcel_stats_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
