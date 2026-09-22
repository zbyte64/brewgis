MODEL (
  name brewgis.census.tiger_block_groups_raw,
  kind FULL,
  description 'PostGIS bridge materializing the DuckDB staging VIEW of TIGER/Line block group boundaries.',
  column_descriptions (
    geoid = 'Block group GEOID from STATEFP, COUNTYFP, TRACTCE and BLKGRPCE (12-digit FIPS).',
    geometry = 'Block group boundary from the DuckDB VIEW with CRS tagged EPSG:3857 (Web Mercator, meters).',
    wgs84_geometry = 'Block group boundary from the DuckDB VIEW with CRS tagged EPSG:4326 (degrees, EPSG:4326).',
    state_fips = 'Two-digit state FIPS code from STATEFP.',
    vintage = 'TIGER/Line vintage of the source file, either 2023 or 2013.'
  ),
  gateway duckdb
);

-- TIGER Block Groups Bridge — materializes the DuckDB VIEW into PostGIS.
--
-- PostGIS models should use brewgis.census.tiger_block_groups (the PostGIS
-- VIEW wrapping this table) rather than referencing this model directly, to
-- get proper SRID column metadata for index-friendly spatial predicates.

SELECT
  geoid,
  ST_SetCRS(geometry, 'EPSG:3857') AS geometry,
  ST_SetCRS(wgs84_geometry, 'EPSG:4326') AS wgs84_geometry,
  state_fips,
  vintage
FROM duckdb.census.tiger_block_groups;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_tiger_block_groups_raw_geoid_')
  ON @this_model USING btree (geoid);
