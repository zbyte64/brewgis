MODEL (
  name brewgis.staging._tiger_block_groups_raw,
  kind FULL,
  gateway duckdb
);

-- TIGER Block Groups Bridge — materializes the DuckDB VIEW into PostGIS.
--
-- PostGIS models should use brewgis.staging.tiger_block_groups (the PostGIS
-- VIEW wrapping this table) rather than referencing this model directly, to
-- get proper SRID column metadata for index-friendly spatial predicates.

SELECT
  geoid,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  state_fips,
  vintage
FROM duckdb.staging.tiger_block_groups;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_tiger_block_groups_raw_geoid ON @this_model USING btree (geoid);
