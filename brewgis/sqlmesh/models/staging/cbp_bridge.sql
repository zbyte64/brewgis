MODEL (
  name brewgis.staging.cbp_raw,
  kind FULL,
  gateway duckdb
);

-- CBP Raw Bridge — materializes the DuckDB VIEW (which reads from Census CBP API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference it.

SELECT * FROM duckdb.staging.cbp_raw;
