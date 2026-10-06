MODEL (
  name duckdb.california.building_climate_zones,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CEC Title-24 Building Climate Zones FeatureServer for all of California through arcgis_query.',
  column_descriptions (
    title24_zone = 'Building Climate Zone number (the layer''s BZone attribute, 1-16) the polygon belongs to.',
    geometry = 'Zone polygon returned by arcgis_query in EPSG:4326 lon/lat; the layer mixes Polygon and MultiPolygon features.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    title24_zone INTEGER,
    geometry GEOMETRY
  )
);

-- CEC Building Climate Zones (Title-24) — DuckDB VIEW over the whole statewide
-- layer. arcgis_query (the arcgis extension) returns the layer's fields as
-- typed columns plus an EPSG:4326 geometry.
--
-- No envelope: the zones are reference geography for the whole state, so a
-- region passes its parcels through the centroids rather than the fetch
-- narrowing itself to one region (Fresno and SACOG read the same rows). The
-- layer held 16 polygons (one per zone, 1-16) when this was written
-- (2026-10-01, verified against the service's returnCountOnly).
--
-- Source: CEC GIS Open Data "California Building Climate Zones"
-- (https://cecgis-caenergy.opendata.arcgis.com/datasets/549017ee96e341d2bbb3dd0c291a9112_0),
-- the FeatureServer behind that item.
--
-- BZone is a text attribute whose values are the numeric zone labels ('1' …
-- '16'), so the cast is safe on every published row.

SELECT
    BZone::INTEGER AS title24_zone,
    geometry
FROM arcgis_query(
    'https://services3.arcgis.com/bWPjFyq029ChCGur/arcgis/rest/services/BuildingClimateZones_CEC_2015/FeatureServer/0'
);
