MODEL (
  name brewgis.fresno.wetlands_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB NWI wetlands fetch, one wetland polygon per row.',
  column_descriptions (
    attribute = 'ATTRIBUTE classification of the NWI record.',
    wetland_type = 'WETLAND_TYPE wetland label of the polygon.',
    acres = 'ACRES attribute of the wetland polygon as published by the source service (acres).',
    geometry = 'Wetland geometry in EPSG:4326, wrapped in ST_SetCRS so the SRID survives the DuckDB-to-PostGIS FDW.'
  ),
  gateway duckdb
);

-- Fresno Wetlands Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/fresno_parcels_bridge.sql.

SELECT
    attribute,
    wetland_type,
    acres,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.wetlands;
