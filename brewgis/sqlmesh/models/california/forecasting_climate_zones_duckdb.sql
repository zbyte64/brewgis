MODEL (
  name duckdb.california.forecasting_climate_zones,
  kind VIEW,
  description 'DuckDB staging VIEW fetching the CEC Forecasting Climate Zones FeatureServer for all of California.',
  column_descriptions (
    fcz_zone = 'CEC electricity-demand Forecasting Climate Zone number (the layer''s FZ_Number, 0-20) the polygon belongs to.',
    fcz_name = 'FZ_Name label of the forecasting climate zone (planning-area name such as SMUD Service Territory).',
    planning_area = 'Plnng_Area utility planning area label the zone belongs to (PG&E, SCE, SDG&E, LADWP, NCNC, …).',
    geometry = 'Zone polygon parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat); the layer mixes Polygon and MultiPolygon features.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    fcz_zone INTEGER,
    fcz_name VARCHAR,
    planning_area VARCHAR,
    geometry GEOMETRY
  )
);

-- CEC Forecasting Climate Zones — DuckDB VIEW that fetches the whole statewide
-- layer via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000).
-- The layer held 28 polygons (21 zones, 0-20, one polygon per zone fragment)
-- when this was written (2026-10-01, verified against the service's
-- returnCountOnly), so one page is the whole set; extra pages would come back
-- empty.
--
-- No envelope: the zones are statewide reference geography shared by every
-- region (see building_climate_zones_duckdb.sql).
--
-- Source: CEC GIS Open Data "California Electricity Demand Forecast Zones"
-- (https://cecgis-caenergy.opendata.arcgis.com/datasets/86fef50f6f344fabbe545e58aec83edd),
-- the FeatureServer behind that item. Zone 0 is the layer's own "Other"
-- planning area (unassigned territory), not a forecasting zone.
--
-- The numbering is the CEC 2015 revision: Sacramento is zone 13 (SMUD Service
-- Territory) and Stockton zone 4 (Central Valley). UrbanFootprint's restored
-- demo table (public.sac_cnty_climate_zones) carries the same Title-24 and ETo
-- ids but a superseded forecasting-zone numbering (Sacramento 6) whose rows
-- also contain non-zone ids (1307, 1310), so this model follows the published
-- CEC layer rather than that table.

SELECT
    feature.properties.FZ_Number::INTEGER AS fcz_zone,
    feature.properties.FZ_Name::VARCHAR AS fcz_name,
    feature.properties.Plnng_Area::VARCHAR AS planning_area,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://services3.arcgis.com/bWPjFyq029ChCGur/arcgis/rest/services/ForecastingClimateZones_CEC_2015/FeatureServer/0/query',
        '1=1',
        'FZ_Number,FZ_Name,Plnng_Area',
        geometry = NULL,
        pages = 1
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
