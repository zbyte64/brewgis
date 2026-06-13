MODEL (
  name brewgis.staging.overture_transport,
  kind FULL,
  gateway duckdb
);

-- Overture Transportation — bridge model that materializes the DuckDB VIEW
-- (which reads GeoParquet from S3) into a PostGIS-accessible table.
--
-- DuckDB ST_Transform to EPSG:4326 follows OGC axis order (lat, lon).
-- PostGIS expects (lon, lat).  ST_FlipCoordinates swaps them so parcel
-- spatial joins work correctly.

SELECT
    ST_SetCRS(ST_FlipCoordinates(geometry), 'EPSG:4326') AS geometry,
    surface,
    class,
    subclass,
    width
FROM duckdb.staging.overture_transport;
