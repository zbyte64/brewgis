MODEL (
  name brewgis.staging.tiger_blocks,
  kind FULL,
  gateway duckdb
);

-- TIGER Blocks Bridge — materializes the DuckDB VIEW into PostGIS.

SELECT
  geoid,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  state_fips,
  vintage
FROM duckdb.staging.tiger_blocks;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_tiger_blocks_raw_geoid_vintage ON @this_model USING btree (geoid, vintage);
