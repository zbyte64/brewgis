MODEL (
  name brewgis.@{region}.acs_bridge,
  kind FULL,
  gateway duckdb,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- ACS Raw Bridge — materializes the DuckDB VIEW (which reads from Census API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference
-- it via cross-gateway reads.
--
-- Replaces the public.acs_raw table previously created by the dlt census pipeline.
-- All columns match the dlt staging schema in external_models/dlt_staging.yaml.

SELECT * FROM duckdb.@{region}.acs_raw;
