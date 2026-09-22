MODEL (
  name brewgis.census.tiger_blocks,
  kind VIEW,
  description 'PostGIS VIEW over the TIGER blocks bridge that restores SRID metadata with ST_SetSRID.',
  column_descriptions (
    geoid = 'Census block GEOID from STATEFP20, COUNTYFP20, TRACTCE20 and BLOCKCE20 (15-digit FIPS).',
    geometry = 'Block boundary MultiPolygon re-tagged as SRID 3857 (Web Mercator, meters).',
    wgs84_geometry = 'Block boundary MultiPolygon re-tagged as SRID 4326 (degrees, EPSG:4326).',
    state_fips = 'Two-digit state FIPS code from STATEFP20.',
    vintage = 'TIGER/Line vintage of the source file, always 2020 for this model.'
  ),
  columns (
    geoid TEXT,
    geometry GEOMETRY(MultiPolygon, 3857),
    wgs84_geometry GEOMETRY(MultiPolygon, 4326),
    state_fips TEXT,
    vintage TEXT
  )
);

-- TIGER Blocks — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID metadata for both Web Mercator and geographic columns.
--
-- The DuckDB bridge (brewgis.census.tiger_blocks_raw) materializes
-- TIGER/Line census block boundaries with ST_SetCRS, then SQLMesh exposes it
-- to PostGIS via FDW. However, the FDW drops SRID metadata, so all geometries
-- arrive as SRID=0.
--
-- This VIEW restores the SRID via ST_SetSRID, enabling downstream PostGIS
-- models to use spatial predicates directly against the indexed geometry
-- columns without function wrappers.

SELECT
  geoid,
  ST_SetSRID(geometry, 3857) AS geometry,
  ST_SetSRID(wgs84_geometry, 4326) AS wgs84_geometry,
  state_fips,
  vintage
FROM brewgis.census.tiger_blocks_raw;
