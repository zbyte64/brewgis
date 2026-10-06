MODEL (
  name brewgis.fresno.farmland_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Important Farmland fetch, one polygon per row.',
  column_descriptions (
    objectid = 'OBJECTID of the farmland polygon, as fetched from the FeatureServer.',
    county = 'County name (County) of the farmland polygon.',
    code = 'Important Farmland class code (Code) published by the Dept of Conservation.',
    geometry = 'Farmland geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.fresno.farmland for the re-tagged column.'
  ),
  gateway duckdb
);

-- Fresno Farmland Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- arcgis_query emits EPSG:4326 geometry (lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    objectid,
    county,
    code,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.farmland;
