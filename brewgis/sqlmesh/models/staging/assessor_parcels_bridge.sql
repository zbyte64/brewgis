MODEL (
  name brewgis.staging.sacog_assessor_parcels_raw,
  kind FULL,
  gateway duckdb
);

-- Assessor Parcels Bridge — materializes the DuckDB VIEW into PostGIS.

SELECT
  apn,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  lotsize,
  landuse,
  zone,
  jurisdiction
FROM duckdb.staging.assessor_parcels;
