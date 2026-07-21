MODEL (
  name brewgis.staging.census_2020_block_raw,
  kind FULL,
  gateway duckdb
);

-- Census 2020 Block Raw Bridge — materializes the DuckDB VIEW (which reads
-- from Census API) into a PostGIS-accessible table so downstream PostGIS
-- models can reference it via cross-gateway reads.
--
-- Replaces the public.census_2020_block_raw table previously created by the
-- dlt census_2020 pipeline.

SELECT * FROM duckdb.staging.census_2020_block_raw;
