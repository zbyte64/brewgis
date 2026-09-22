MODEL (
  name brewgis.fresno.wetlands,
  kind VIEW,
  description 'NWI freshwater wetlands over the Fresno region from the CA Fish and Wildlife BIOS service.',
  column_descriptions (
    attribute = 'ATTRIBUTE classification of the NWI record; the fetch keeps only values containing Fresh.',
    wetland_type = 'WETLAND_TYPE wetland label of the polygon from the NWI record.',
    acres = 'ACRES attribute of the wetland polygon as published by the source service (acres).',
    geom = 'Wetland polygon at SRID 4326, restored with ST_SetSRID from the bridge table geometry.'
  ),
  columns (
    attribute TEXT,
    wetland_type TEXT,
    acres DOUBLE PRECISION,
    geom GEOMETRY(GEOMETRY, 4326)
  )
);

-- Fresno Wetlands — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.fresno.wetlands_raw) materializes the
-- fetched wetlands with ST_SetCRS, then SQLMesh exposes it to PostGIS via
-- FDW. The FDW drops SRID metadata, so all geometries arrive as SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID and renames the geometry column
-- to geom (the convention expected by constraint discounting). The
-- ATTRIBUTE LIKE '%Fresh%' filter yields zero features for the Fresno
-- envelope, so this table is legitimately empty.

SELECT
    attribute,
    wetland_type,
    acres,
    ST_SetSRID(geometry, 4326) AS geom
FROM brewgis.fresno.wetlands_raw;
