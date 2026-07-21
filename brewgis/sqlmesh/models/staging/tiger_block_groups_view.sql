MODEL (
  name brewgis.staging.tiger_block_groups,
  kind VIEW,
  columns (
    geoid TEXT,
    geometry GEOMETRY(MultiPolygon, 4326),
    state_fips TEXT,
    vintage TEXT
  )
);

-- TIGER Block Groups — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID=4326 metadata.
--
-- The DuckDB bridge (brewgis.staging._tiger_block_groups_raw) materializes
-- TIGER/Line block group boundaries with ST_FlipCoordinates and ST_SetCRS,
-- then SQLMesh exposes it to PostGIS via FDW. However, the FDW drops SRID
-- metadata, so all geometries arrive as SRID=0.
--
-- This VIEW restores the SRID via ST_SetSRID and declares the column type
-- as GEOMETRY(MultiPolygon, 4326), enabling downstream PostGIS models to
-- use spatial predicates (ST_Within, ST_Intersects, etc.) directly against
-- the indexed geometry column without function wrappers.

SELECT
  geoid,
  ST_SetSRID(geometry, 4326) AS geometry,
  state_fips,
  vintage
FROM brewgis.staging._tiger_block_groups_raw;
