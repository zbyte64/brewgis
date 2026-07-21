MODEL (
  name duckdb.staging.assessor_parcels,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    apn VARCHAR,
    landuse VARCHAR,
    zone VARCHAR,
    lotsize DOUBLE,
    jurisdiction VARCHAR,
    geometry GEOMETRY
  )
);

-- Sacramento County assessor parcels — DuckDB reads from local GeoParquet.
--
-- The GeoParquet file is created by assessor_fetcher.write_to_geoparquet(),
-- which downloads parcel geometries from ArcGIS REST services.
-- DuckDB's ST_Transform to EPSG:4326 follows OGC axis order (lat, lon).
-- PostGIS expects (lon, lat). Downstream bridge model flips coordinates.

SELECT
  apn,
  landuse,
  zone,
  lotsize,
  jurisdiction,
  geometry
FROM read_parquet('/app/planning/assessor/assessor_parcels.parquet');
