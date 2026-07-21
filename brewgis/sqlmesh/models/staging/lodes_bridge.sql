MODEL (
  name brewgis.staging.lodes_raw,
  kind FULL,
  gateway duckdb
);

-- LODES Raw Bridge — materializes the DuckDB VIEW (which reads gzipped CSV
-- from CES FTP via httpfs) into a PostGIS-accessible table so downstream
-- PostGIS models can reference it via cross-gateway reads.
--
-- Replaces the public.lodes_raw table previously created by the dlt lehd pipeline.
-- All columns match the dlt staging schema in external_models/dlt_staging.yaml.

SELECT * FROM duckdb.staging.lodes_raw;
