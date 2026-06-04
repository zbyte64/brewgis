MODEL (
  name brewgis.nlcd.parcels_wm,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (id),
    batch_size 100000
  ),
  audits (
    not_null(columns := (id))
  )
);


-- Web Mercator projection of parcel geometries for NLCD zonal statistics.
-- NLCD rasters are in EPSG:3857, so parcels must be projected to match.
-- Reads from the configured parcel table (@parcel_table in config.py).
-- Reads from the comparison parcels table.

SELECT
    parcel_id AS id,
    ST_Transform(geometry, 3857) AS geometry
FROM public.sacog_comparison_parcels
WHERE geometry IS NOT NULL
