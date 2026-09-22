MODEL (
  name brewgis.census.tiger_blocks_raw,
  kind FULL,
  description 'PostGIS bridge materializing the DuckDB staging VIEW of TIGER/Line 2020 block boundaries.',
  column_descriptions (
    geoid = 'Census block GEOID from STATEFP20, COUNTYFP20, TRACTCE20 and BLOCKCE20 (15-digit FIPS).',
    geometry = 'Block boundary from the DuckDB VIEW with CRS tagged EPSG:3857 (Web Mercator, meters).',
    wgs84_geometry = 'Block boundary from the DuckDB VIEW with CRS tagged EPSG:4326 (degrees, EPSG:4326).',
    state_fips = 'Two-digit state FIPS code from STATEFP20.',
    vintage = 'TIGER/Line vintage of the source file, always 2020 for this model.'
  ),
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
