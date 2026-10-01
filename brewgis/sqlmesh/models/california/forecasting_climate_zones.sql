MODEL (
  name brewgis.california.forecasting_climate_zones,
  kind VIEW,
  description 'PostGIS VIEW over the Forecasting Climate Zones bridge that restores SRID metadata with ST_SetSRID.',
  column_descriptions (
    fcz_zone = 'CEC electricity-demand Forecasting Climate Zone number (0-20) the polygon belongs to; the zone a parcel falls in is the one whose polygon contains its centroid.',
    fcz_name = 'FZ_Name label of the forecasting climate zone.',
    planning_area = 'Plnng_Area utility planning area label of the zone.',
    geometry = 'Zone boundary re-tagged as SRID 4326 (degrees, EPSG:4326) and normalized to MultiPolygon.'
  ),
  columns (
    fcz_zone INTEGER,
    fcz_name TEXT,
    planning_area TEXT,
    geometry GEOMETRY(MultiPolygon, 4326)
  )
);

-- California Forecasting Climate Zones — PostGIS VIEW wrapping the DuckDB
-- bridge with a real SRID.
--
-- The bridge (brewgis.california.forecasting_climate_zones_raw) materializes the
-- fetched zones through DuckDB, and that transfer writes SRID-less WKB. This
-- VIEW restores the SRID with ST_SetSRID and normalizes the geometry kind with
-- ST_Multi (the published layer mixes Polygon and MultiPolygon features).
--
-- Consumers must index ST_SetSRID(geometry, 4326) on the *bridge* table, not the
-- bare column: the FDW inlines this VIEW's expression (see
-- assessor/parcel_block_groups.sql).

SELECT
    fcz_zone,
    fcz_name,
    planning_area,
    ST_Multi(ST_SetSRID(geometry, 4326)) AS geometry
FROM brewgis.california.forecasting_climate_zones_raw;
