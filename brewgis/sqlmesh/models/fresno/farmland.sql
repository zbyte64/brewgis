MODEL (
  name brewgis.fresno.farmland,
  kind VIEW,
  columns (
    objectid INTEGER,
    county TEXT,
    code TEXT,
    geom GEOMETRY(GEOMETRY, 4326)
  )
);

-- Fresno Farmland — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.staging._fresno_farmland_raw) materializes the
-- fetched Important Farmland with ST_SetCRS, then SQLMesh exposes it to
-- PostGIS via FDW. The FDW drops SRID metadata, so all geometries arrive as
-- SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID and renames the geometry column
-- to geom (the convention expected by constraint discounting).

SELECT
    objectid,
    county,
    code,
    ST_SetSRID(geometry, 4326) AS geom
FROM brewgis.staging._fresno_farmland_raw;
