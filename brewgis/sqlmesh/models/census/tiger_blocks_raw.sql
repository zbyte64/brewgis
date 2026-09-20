MODEL (
  name brewgis.census.tiger_blocks_raw,
  kind FULL,
  gateway duckdb
);

-- TIGER Blocks Bridge — materializes the DuckDB VIEW into PostGIS.
--
-- PostGIS models should use brewgis.census.tiger_blocks (the PostGIS
-- VIEW wrapping this table) rather than referencing this model directly, to
-- get proper SRID column metadata for index-friendly spatial predicates.

SELECT
  geoid,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  state_fips,
  vintage
FROM duckdb.census.tiger_blocks;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_tiger_blocks_raw_geoid_vintage_')
  ON @this_model USING btree (geoid, vintage);
