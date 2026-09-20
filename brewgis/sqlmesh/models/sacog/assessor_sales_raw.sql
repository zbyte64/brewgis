MODEL (
  name brewgis.sacog.assessor_sales_raw,
  kind FULL,
  gateway duckdb
);

-- Assessor Sales Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.sacog_assessor_sales_raw table previously created
-- by the dlt assessor pipeline.

SELECT * FROM duckdb.sacog.assessor_sales;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sacog_assessor_sales_raw_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_sacog_assessor_sales_raw_property_type_')
  ON @this_model USING btree (property_type);
