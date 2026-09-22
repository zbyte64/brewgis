MODEL (
  name brewgis.nlcd.parcels_wm,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (parcel_id),
    batch_size 100000
  ),
  description 'Web mercator (EPSG:3857) parcel geometries for NLCD zonal statistics, one row per parcel_id.',
  column_descriptions (
    parcel_id = 'Parcel identifier from the source comparison parcels table (sacog_comparison_parcels).',
    geometry = 'Parcel geometry transformed to web mercator (EPSG:3857 by default) to match the NLCD raster CRS.'
  ),
  audits (
    not_null(columns := (parcel_id))
  )
);


-- Web Mercator projection of parcel geometries for NLCD zonal statistics.
-- NLCD rasters are in EPSG:3857, so parcels must be projected to match.
-- Reads from the configured parcel table (@parcel_table in config.py).
-- Reads from the comparison parcels table.

SELECT
    parcel_id,
    ST_Transform(geometry, @VAR('wm_srid', 3857)) AS geometry
FROM public.sacog_comparison_parcels
WHERE geometry IS NOT NULL;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_parcels_wm_geometry_')
  ON @this_model USING GIST (geometry);
