MODEL (
  name duckdb.california.building_climate_zones,
  kind VIEW,
  description 'DuckDB staging VIEW fetching the CEC Title-24 Building Climate Zones FeatureServer for all of California.',
  column_descriptions (
    title24_zone = 'Building Climate Zone number (the layer''s BZone attribute, 1-16) the polygon belongs to.',
    geometry = 'Zone polygon parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat); the layer mixes Polygon and MultiPolygon features.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    title24_zone INTEGER,
    geometry GEOMETRY
  )
);

-- CEC Building Climate Zones (Title-24) — DuckDB VIEW that fetches the whole
-- statewide layer via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000)
-- as a constant list_value(...) literal — DuckDB does not accept subqueries
-- or lateral columns inside table functions, so the page list cannot be read
-- from another relation. The page count is declared by the call site, never
-- probed, so rendering this model never touches the network (see
-- @arcgis_page_urls).
--
-- No envelope: the zones are reference geography for the whole state, so a
-- region passes its parcels through the centroids rather than the fetch
-- narrowing itself to one region (Fresno and SACOG read the same rows). The
-- layer held 16 polygons (one per zone, 1-16) when this was written
-- (2026-10-01, verified against the service's returnCountOnly), so one page is
-- the whole set; extra pages would come back empty.
--
-- Source: CEC GIS Open Data "California Building Climate Zones"
-- (https://cecgis-caenergy.opendata.arcgis.com/datasets/549017ee96e341d2bbb3dd0c291a9112_0),
-- the FeatureServer behind that item.
--
-- BZone is a text attribute whose values are the numeric zone labels ('1' …
-- '16'), so the cast is safe on every published row.

SELECT
    feature.properties.BZone::INTEGER AS title24_zone,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://services3.arcgis.com/bWPjFyq029ChCGur/arcgis/rest/services/BuildingClimateZones_CEC_2015/FeatureServer/0/query',
        '1=1',
        'BZone',
        geometry = NULL,
        pages = 1
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
