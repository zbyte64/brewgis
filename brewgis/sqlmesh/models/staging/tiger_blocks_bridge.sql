MODEL (
  name brewgis.staging.tiger_blocks,
  kind FULL,
  gateway duckdb
);

-- TIGER Blocks Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.tiger_blocks table previously created by the dlt
-- tiger_block pipeline. DuckDB ST_Transform to EPSG:4326 follows OGC
-- axis order (lat, lon). PostGIS expects (lon, lat).
-- ST_FlipCoordinates swaps them so spatial joins work correctly.

SELECT
  geoid,
  ST_SetCRS(ST_FlipCoordinates(geometry), 'EPSG:4326') AS geometry,
  state_fips,
  vintage
FROM duckdb.staging.tiger_blocks;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_tiger_blocks_raw_geoid_vintage ON @this_model USING btree (geoid, vintage);
