MODEL (
  name brewgis.staging.tiger_block_groups,
  kind FULL,
  gateway duckdb
);

-- TIGER Block Groups Bridge — materializes the DuckDB VIEW (which reads from
-- local GeoParquet) into a PostGIS-accessible table.
--
-- Replaces the public.tiger_block_groups table previously created by the dlt
-- tiger_bg pipeline.

SELECT
  geoid,
  ST_SetCRS(ST_FlipCoordinates(geometry), 'EPSG:4326') AS geometry,
  state_fips,
  vintage
FROM duckdb.staging.tiger_block_groups;
