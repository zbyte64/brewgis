MODEL (
  name brewgis.california.building_climate_zones_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Title-24 Building Climate Zones fetch, one zone polygon per row.',
  column_descriptions (
    title24_zone = 'Building Climate Zone number (1-16) the polygon belongs to.',
    geometry = 'Zone geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.california.building_climate_zones for the re-tagged column.'
  ),
  gateway duckdb
);

-- California Building Climate Zones Bridge — materializes the DuckDB fetch VIEW
-- into PostGIS.
--
-- arcgis_query emits EPSG:4326 geometry (lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    title24_zone,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.california.building_climate_zones;
