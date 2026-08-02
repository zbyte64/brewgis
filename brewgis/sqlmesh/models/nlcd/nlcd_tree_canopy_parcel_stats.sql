MODEL (
  name brewgis.nlcd.nlcd_tree_canopy_parcel_stats,
  kind FULL,
  gateway duckdb,
  dialect duckdb,
  audits (
    not_null(columns := (parcel_id))
  ),
  depends_on (
    brewgis.public.sacog_comparison_parcels
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
-- The GeoTIFF URL is computed dynamically from the parcel bbox and
-- fetched via httpfs with cache_httpfs handling on-disk caching.
--
-- Depends on:
--   - @nlcd_parcel_source: PostGIS parcel table with geometry in
--     EPSG:@nlcd_parcel_srid

-- pre_statements
  SET VARIABLE nlcd_tree_canopy_url = (
    SELECT
      'https://www.mrlc.gov/geoserver/wcs?service=WCS&version=2.0.1&request=GetCoverage'
      || '&CoverageId=mrlc_download__nlcd_tcc_conus_' || @nlcd_tree_canopy_year || '_v2021-4'
      || '&subset=X(' || west || ',' || east || ')'
      || '&subset=Y(' || south || ',' || north || ')'
      || '&format=image/geotiff'
    FROM (
      SELECT
        ST_XMin(ST_Extent(xf.geom_5070)) AS west,
        ST_YMin(ST_Extent(xf.geom_5070)) AS south,
        ST_XMax(ST_Extent(xf.geom_5070)) AS east,
        ST_YMax(ST_Extent(xf.geom_5070)) AS north
      FROM (
        SELECT ST_Transform(
          ST_SetCRS(geometry, 'EPSG:' || @nlcd_parcel_srid),
          'EPSG:5070'
        ) AS geom_5070
        FROM @nlcd_parcel_source
        WHERE geometry IS NOT NULL
        LIMIT 1
      ) xf
    )
  );

WITH
-- Read NLCD Tree Canopy pixels from the cached GeoTIFF.
-- Geometry is in EPSG:5070 (native CRS of the WCS coverage).
tcc_pixels AS (
    SELECT
        x,
        y,
        geometry AS geom_5070,
        band_1 AS canopy_pct  -- UTINYINT 0-100, 255=NoData
    FROM RT_ReadCells(getvariable('nlcd_tree_canopy_url'))
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
    FROM brewgis.public.sacog_comparison_parcels
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
    FROM brewgis.public.sacog_comparison_parcels
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
