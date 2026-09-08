MODEL (
  name brewgis.@{region}.nlcd_parcel_stats,
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

-- NLCD Parcel Statistics Model (DuckDB raster extension)
--
-- Reads the NLCD land cover GeoTIFF raster directly from the MRLC WCS
-- endpoint via DuckDB's RT_ReadCells (powered by GDAL/raster extension),
-- spatially joins each pixel to its parcel, and computes per-parcel:
--   - land_development_category (majority NLCD class mapped to label)
--   - impervious_fraction (weighted average of impervious factors)
--
-- The GeoTIFF URL is computed dynamically from the parcel bbox and
-- fetched via httpfs with cache_httpfs handling on-disk caching.
--
-- Region-scoped parcel source (blueprint var @nlcd_parcel_source), e.g.
-- sacog: public.sacog_comparison_parcels (geometry EPSG:3310)
-- fresno: brewgis.staging.fresno_parcels (raw ArcGIS fetch, lon/lat 4326,
-- geometry stored without SRID -> @nlcd_parcel_srid = 4326).
-- NLCD is a national dataset, so every region's parcels get real stats.

-- pre_statements
-- SELECT RT_GdalConfig('GDAL_DISABLE_READDIR_ON_OPEN', 'EMPTY_DIR');

  SET VARIABLE nlcd_land_cover_url = (
    SELECT
      'https://www.mrlc.gov/geoserver/wcs?service=WCS&version=2.0.1&request=GetCoverage'
      || '&CoverageId=mrlc_download__NLCD_' || @nlcd_land_cover_year || '_Land_Cover_L48'
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
-- Read NLCD raster pixels from the cached GeoTIFF.
-- The geometry column from RT_ReadCells is already in EPSG:5070
-- (the native CRS of the NLCD WCS coverage).
nlcd_pixels AS (
    SELECT
        x,
        y,
        geometry AS geom_5070,
        band_1::INTEGER AS nlcd_class
    FROM RT_ReadCells(getvariable('nlcd_land_cover_url'))
    WHERE band_1 != 0  -- NoData / background
),

-- Get parcel geometries and project to EPSG:5070 (raster CRS).
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

-- Spatial join: each pixel belongs to at most one parcel.
-- DuckDB spatial uses an R-tree index for ST_Contains.
pixel_parcels AS (
    SELECT
        p.parcel_id,
        px.nlcd_class
    FROM nlcd_pixels px
    JOIN parcels_5070 p
        ON ST_Contains(p.geom_5070, px.geom_5070)
),

-- Count pixels per NLCD class per parcel.
per_parcel_counts AS (
    SELECT
        parcel_id,
        nlcd_class,
        COUNT(*) AS pixel_count
    FROM pixel_parcels
    GROUP BY parcel_id, nlcd_class
),

-- Majority NLCD class per parcel.
majority_class AS (
    SELECT DISTINCT ON (parcel_id)
        parcel_id,
        nlcd_class AS majority_nlcd_class
    FROM per_parcel_counts
    ORDER BY parcel_id, pixel_count DESC
),

-- Weighted impervious fraction based on NLCD class factors.
impervious_frac AS (
    SELECT
        parcel_id,
        CASE
            WHEN SUM(pixel_count) > 0
            THEN SUM(pixel_count * CASE nlcd_class
                WHEN 11 THEN 0.0    -- open water
                WHEN 12 THEN 0.0    -- perennial ice/snow
                WHEN 21 THEN 0.10   -- developed, open space
                WHEN 22 THEN 0.30   -- developed, low intensity
                WHEN 23 THEN 0.60   -- developed, medium intensity
                WHEN 24 THEN 0.85   -- developed, high intensity
                WHEN 31 THEN 0.50   -- barren land (rock/sand/clay)
                WHEN 41 THEN 0.0    -- deciduous forest
                WHEN 42 THEN 0.0    -- evergreen forest
                WHEN 43 THEN 0.0    -- mixed forest
                WHEN 51 THEN 0.0    -- dwarf scrub
                WHEN 52 THEN 0.0    -- shrub/scrub
                WHEN 71 THEN 0.0    -- grassland/herbaceous
                WHEN 72 THEN 0.0    -- sedge/herbaceous
                WHEN 73 THEN 0.0    -- lichens
                WHEN 74 THEN 0.0    -- moss
                WHEN 81 THEN 0.0    -- pasture/hay
                WHEN 82 THEN 0.0    -- cultivated crops
                WHEN 90 THEN 0.0    -- woody wetlands
                WHEN 95 THEN 0.0    -- emergent herbaceous wetlands
                ELSE 0.0
            END) / SUM(pixel_count)
            ELSE 0.0
        END AS impervious_fraction
    FROM per_parcel_counts
    GROUP BY parcel_id
),

-- All parcels (including those with zero NLCD overlap).
all_parcels AS (
    SELECT @{nlcd_parcel_id} AS parcel_id
    FROM @ref_model(@nlcd_parcel_source)
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
  CREATE INDEX IF NOT EXISTS idx_nlcd_parcel_stats_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
