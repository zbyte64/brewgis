MODEL (
  name brewgis.fresno.wetlands_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB NWI wetlands fetch, one wetland polygon per row.',
  column_descriptions (
    attribute = 'ATTRIBUTE classification of the NWI record.',
    wetland_type = 'WETLAND_TYPE wetland label of the polygon.',
    acres = 'ACRES attribute of the wetland polygon as published by the source service (acres).',
    geometry = 'Wetland geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.fresno.wetlands for the re-tagged column.'
  ),
  gateway duckdb
);

-- Fresno Wetlands Bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- arcgis_query emits EPSG:4326 geometry (lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    attribute,
    wetland_type,
    acres,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.fresno.wetlands;
