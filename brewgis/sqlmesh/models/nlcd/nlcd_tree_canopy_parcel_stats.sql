MODEL (
  name brewgis.nlcd.nlcd_tree_canopy_parcel_stats,
  kind FULL,
  gateway duckdb,
  dialect duckdb,
  audits (
    not_null(columns := (parcel_id))
  )
);

-- NLCD Tree Canopy Parcel Statistics Model (DuckDB raster extension)
--
-- Reads the NLCD USFS Tree Canopy Cover GeoTIFF raster via DuckDB's
-- RT_ReadCells, spatially joins each pixel to its parcel, and
-- computes per-parcel mean tree canopy fraction (0-100%).
--
-- The tree canopy product contains continuous 0-100% pixel values
-- at 30m resolution.  The WCS coverage stores values as UTINYINT
-- (0-254 range, where 255 = NoData).
--
-- Depends on:
--   - @nlcd_tree_canopy_raster_path: local cached GeoTIFF
--   - @nlcd_parcel_source: PostGIS parcel table with geometry in
--     EPSG:@nlcd_parcel_srid

WITH
-- Read NLCD Tree Canopy pixels from the cached GeoTIFF.
-- Geometry is in EPSG:5070 (native CRS of the WCS coverage).
tcc_pixels AS (
    SELECT
        x,
        y,
        geometry AS geom_5070,
        band_1 AS canopy_pct  -- UTINYINT 0-100, 255=NoData
    FROM RT_ReadCells(@nlcd_tree_canopy_raster_path)
    WHERE band_1 != 255 AND band_1 IS NOT NULL
),

-- Get parcel geometries projected to EPSG:5070.
parcels_5070 AS (
    SELECT
        id AS parcel_id,
        ST_Transform(
            ST_SetCRS(geometry, 'EPSG:' || @nlcd_parcel_srid),
            'EPSG:5070'
        ) AS geom_5070
    FROM brewgis.@nlcd_parcel_source
    WHERE geometry IS NOT NULL
),

-- Spatial join: pixels to parcels via point-in-polygon.
pixel_parcels AS (
    SELECT
        p.parcel_id,
        px.canopy_pct
    FROM tcc_pixels px
    JOIN parcels_5070 p
        ON ST_Contains(p.geom_5070, px.geom_5070)
),

-- Mean canopy fraction per parcel.
per_parcel_mean AS (
    SELECT
        parcel_id,
        AVG(canopy_pct::DOUBLE) AS tree_canopy_pct
    FROM pixel_parcels
    GROUP BY parcel_id
),

-- All parcels (including those with no canopy overlap).
all_parcels AS (
    SELECT id AS parcel_id
    FROM brewgis.@nlcd_parcel_source
    WHERE geometry IS NOT NULL
)

SELECT
    ap.parcel_id,
    GREATEST(0.0, LEAST(100.0, s.tree_canopy_pct)) AS tree_canopy_fraction
FROM all_parcels ap
LEFT JOIN per_parcel_mean s ON ap.parcel_id = s.parcel_id;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_nlcd_tree_canopy_parcel_stats_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
