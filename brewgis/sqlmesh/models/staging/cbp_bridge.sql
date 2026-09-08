MODEL (
  name brewgis.@{region}.cbp_raw,
  kind FULL,
  gateway duckdb,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- CBP Raw Bridge — materializes the DuckDB VIEW (which reads from Census CBP API)
-- into a PostGIS-accessible table so downstream PostGIS models can reference it.

SELECT * FROM duckdb.@{region}.cbp_raw;
