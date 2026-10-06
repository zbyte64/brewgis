MODEL (
  name brewgis.california.forecasting_climate_zones_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Forecasting Climate Zones fetch, one zone polygon per row.',
  column_descriptions (
    fcz_zone = 'CEC electricity-demand Forecasting Climate Zone number (0-20) the polygon belongs to.',
    fcz_name = 'FZ_Name label of the forecasting climate zone.',
    planning_area = 'Plnng_Area utility planning area label of the zone.',
    geometry = 'Zone geometry in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read brewgis.california.forecasting_climate_zones for the re-tagged column.'
  ),
  gateway duckdb
);

-- California Forecasting Climate Zones Bridge — materializes the DuckDB fetch
-- VIEW into PostGIS.
--
-- arcgis_query emits EPSG:4326 geometry (lon/lat), but the
-- DuckDB-to-PostGIS transfer writes SRID-less WKB: the ST_SetCRS this SELECT
-- applies is not carried over, so the geometry lands as SRID 0 (measured; the
-- probe is recorded in osm/food_pois_raw.sql).

SELECT
    fcz_zone,
    fcz_name,
    planning_area,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.california.forecasting_climate_zones;
