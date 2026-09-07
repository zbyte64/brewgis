MODEL (
  name brewgis.fresno.city_boundary,
  kind VIEW,
  columns (
    objectid INTEGER,
    agency_cod TEXT,
    agency_nam TEXT,
    geom GEOMETRY(GEOMETRY, 4326)
  )
);

-- Fresno City Boundary — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.staging._fresno_city_boundary_raw) materializes
-- the fetched city limits with ST_SetCRS, then SQLMesh exposes it to PostGIS
-- via FDW. The FDW drops SRID metadata, so all geometries arrive as SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID and renames the geometry column
-- to geom (the convention expected by constraint discounting).

SELECT
    objectid,
    agency_cod,
    agency_nam,
    ST_SetSRID(geometry, 4326) AS geom
FROM brewgis.staging._fresno_city_boundary_raw;
