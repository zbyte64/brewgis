MODEL (
  name duckdb.california.forecasting_climate_zones,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CEC Forecasting Climate Zones FeatureServer for all of California through arcgis_query.',
  column_descriptions (
    fcz_zone = 'CEC electricity-demand Forecasting Climate Zone number (the layer''s FZ_Number, 0-20) the polygon belongs to.',
    fcz_name = 'FZ_Name label of the forecasting climate zone (planning-area name such as SMUD Service Territory).',
    planning_area = 'Plnng_Area utility planning area label the zone belongs to (PG&E, SCE, SDG&E, LADWP, NCNC, …).',
    geometry = 'Zone polygon returned by arcgis_query in EPSG:4326 lon/lat; the layer mixes Polygon and MultiPolygon features.'
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

-- CEC Forecasting Climate Zones — DuckDB VIEW over the whole statewide layer.
-- arcgis_query (the arcgis extension) returns the layer's fields as typed
-- columns plus an EPSG:4326 geometry. The layer held 28 polygons (21 zones,
-- 0-20, one polygon per zone fragment) when this was written (2026-10-01,
-- verified against the service's returnCountOnly).
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
--
-- FZ_Number is published as a Single (FLOAT) field holding whole zone numbers,
-- so the cast to INTEGER is exact.

SELECT
    FZ_Number::INTEGER AS fcz_zone,
    FZ_Name AS fcz_name,
    Plnng_Area AS planning_area,
    geometry
FROM arcgis_query(
    'https://services3.arcgis.com/bWPjFyq029ChCGur/arcgis/rest/services/ForecastingClimateZones_CEC_2015/FeatureServer/0'
);
