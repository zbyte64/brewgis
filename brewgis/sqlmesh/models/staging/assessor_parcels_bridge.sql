MODEL (
  name brewgis.staging.sacog_assessor_parcels_raw,
  kind FULL,
  gateway duckdb
);

-- Assessor Parcels Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.sacog_assessor_parcels_raw table previously created
-- by the dlt assessor pipeline.

SELECT
  apn,
  ST_SetCRS(ST_FlipCoordinates(geometry), 'EPSG:4326') AS geometry,
  lotsize,
  landuse,
  zone,
  jurisdiction
FROM duckdb.staging.assessor_parcels;
