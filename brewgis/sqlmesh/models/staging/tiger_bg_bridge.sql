MODEL (
  name brewgis.staging._tiger_block_groups_raw,
  kind FULL,
  gateway duckdb
);

-- TIGER Block Groups Bridge — materializes the DuckDB VIEW (which reads from
-- Census TIGER/Line shapefiles) into a DuckDB table exposed to PostGIS via FDW.
--
-- The DuckDB model ST_Transform(geom, 'EPSG:4326') follows OGC axis order and
-- returns (lat, lon). ST_FlipCoordinates restores (lon, lat) for PostGIS
-- compatibility. ST_SetCRS tags the geometry with EPSG:4326 metadata inside
-- DuckDB.
--
-- PostGIS models should use brewgis.staging.tiger_block_groups (the PostGIS
-- VIEW wrapping this table) rather than referencing this model directly, to
-- get proper SRID=4326 column metadata for index-friendly spatial predicates.

SELECT
  geoid,
  ST_SetCRS(ST_FlipCoordinates(geometry), 'EPSG:4326') AS geometry,
  state_fips,
  vintage
FROM duckdb.staging.tiger_block_groups;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_tiger_block_groups_raw_geoid ON @this_model USING btree (geoid);
