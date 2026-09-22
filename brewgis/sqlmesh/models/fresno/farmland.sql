MODEL (
  name brewgis.fresno.farmland,
  kind VIEW,
  description 'California Important Farmland for Fresno County from the CA Dept of Conservation FeatureServer.',
  column_descriptions (
    objectid = 'OBJECTID of the farmland polygon in the CA Dept of Conservation Important Farmland FeatureServer.',
    county = 'County name (County) of the farmland polygon; the fetch keeps County values matching Fresno.',
    code = 'Important Farmland class code (Code) assigned by the Dept of Conservation.',
    geom = 'Farmland polygon at SRID 4326, restored with ST_SetSRID from the bridge table geometry.'
  ),
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
-- The DuckDB bridge (brewgis.fresno.farmland_raw) materializes the
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
FROM brewgis.fresno.farmland_raw;
