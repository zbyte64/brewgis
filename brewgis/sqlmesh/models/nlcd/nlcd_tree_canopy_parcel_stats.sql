MODEL (
  name brewgis.@{region}.nlcd_tree_canopy_parcel_stats,
  kind FULL,
  gateway duckdb,
  dialect duckdb,
  audits (
    not_null(columns := (parcel_id))
  ),
  blueprints (
    (
      region := sacog,
      nlcd_parcel_source := 'brewgis.public.sacog_comparison_parcels',
      nlcd_parcel_srid := 3310,
      nlcd_parcel_id := 'id'
    ),
    (
      region := fresno,
      nlcd_parcel_source := 'brewgis.staging.fresno_parcels',
      nlcd_parcel_srid := 4326,
      nlcd_parcel_id := 'parcel_id'
    )
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
-- SELECT RT_GdalConfig('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR');

  SET VARIABLE nlcd_tree_canopy_url = (
    SELECT
      'https://www.mrlc.gov/geoserver/wcs?service=WCS&version=2.0.1&request=GetCoverage'
      || '&CoverageId=mrlc_download__nlcd_tcc_conus_' || @nlcd_tree_canopy_year || '_v2021-4'
      || '&subset=X(' || west || ',' || east || ')'
      || '&subset=Y(' || south || ',' || north || ')'
      || '&format=image/geotiff'
    FROM (
      SELECT
        ST_XMin(ST_Extent_Agg(xf.geom_5070)) AS west,
        ST_YMin(ST_Extent_Agg(xf.geom_5070)) AS south,
        ST_XMax(ST_Extent_Agg(xf.geom_5070)) AS east,
        ST_YMax(ST_Extent_Agg(xf.geom_5070)) AS north
      FROM (
        SELECT ST_Transform(
          ST_SetCRS(geometry, 'EPSG:' || @nlcd_parcel_srid),
          'EPSG:' || @nlcd_parcel_srid,
          'EPSG:5070',
          true  -- always_xy: see parcels_5070 CTE note
        ) AS geom_5070
        FROM @ref_model(@nlcd_parcel_source)
        WHERE geometry IS NOT NULL
        -- NOTE: no LIMIT here — the WCS GetCoverage must span the FULL
        -- region parcel extent, otherwise only one parcel's raster slice is
        -- fetched and every other parcel silently falls back to defaults.
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
        @{nlcd_parcel_id} AS parcel_id,
        ST_Transform(
            ST_SetCRS(geometry, 'EPSG:' || @nlcd_parcel_srid),
            'EPSG:' || @nlcd_parcel_srid,
            'EPSG:5070',
            true  -- always_xy: source coords are (lon, lat); EPSG:4326 axis
                  -- order is (lat, lon) and duckdb honours it, producing inf
                  -- without this flag (fresno raw parcels are lon/lat 4326).
        ) AS geom_5070
    FROM @ref_model(@nlcd_parcel_source)
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
    SELECT @{nlcd_parcel_id} AS parcel_id
    FROM @ref_model(@nlcd_parcel_source)
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
