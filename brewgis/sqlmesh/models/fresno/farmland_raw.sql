MODEL (
  name brewgis.fresno.farmland_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Important Farmland fetch, one polygon per row.',
  column_descriptions (
    objectid = 'OBJECTID of the farmland polygon, as fetched from the FeatureServer.',
    county = 'County name (County) of the farmland polygon.',
    code = 'Important Farmland class code (Code) published by the Dept of Conservation.',
    geometry = 'Farmland geometry in EPSG:4326, wrapped in ST_SetCRS so the SRID survives the DuckDB-to-PostGIS FDW.'
  ),
  gateway duckdb
);

-- Fresno Farmland Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Read emits EPSG:4326 geometry (GeoJSON lon/lat). ST_SetCRS
-- records the SRID explicitly because the DuckDB→PostGIS FDW drops SRID
-- metadata (all geometries arrive as SRID 0), mirroring
-- staging/fresno_parcels_bridge.sql.

SELECT
    objectid,
    county,
    code,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.farmland;
