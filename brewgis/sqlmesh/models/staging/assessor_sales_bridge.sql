MODEL (
  name brewgis.staging.sacog_assessor_sales_raw,
  kind FULL,
  gateway duckdb
);

-- Assessor Sales Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.sacog_assessor_sales_raw table previously created
-- by the dlt assessor pipeline.

SELECT * FROM duckdb.staging.assessor_sales;
