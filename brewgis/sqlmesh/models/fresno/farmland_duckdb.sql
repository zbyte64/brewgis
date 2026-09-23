MODEL (
  name duckdb.fresno.farmland,
  kind VIEW,
  description 'DuckDB staging VIEW fetching the CA Important Farmland FeatureServer for Fresno County.',
  column_descriptions (
    objectid = 'OBJECTID of the farmland polygon from the FeatureServer feature properties.',
    county = 'County name (County) from the FeatureServer feature properties; the fetch keeps Fresno.',
    code = 'Important Farmland class code (Code) from the FeatureServer feature properties.',
    geometry = 'Farmland polygon parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat).'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    objectid INTEGER,
    county VARCHAR,
    code VARCHAR,
    geometry GEOMETRY
  )
);

-- California Important Farmland (Fresno County) — DuckDB VIEW that fetches
-- and parses every page of the CA Dept of Conservation Important Farmland
-- FeatureServer via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000)
-- as a constant list_value(...) literal — DuckDB does not accept subqueries
-- or lateral columns inside table functions, so the page list cannot be read
-- from another relation. The page count is declared by the call site, never
-- probed, so rendering this model never touches the network (see
-- @arcgis_page_urls). The county-wide farmland set had 10,495 features = 6
-- pages when this was written (2026-09-23); the declared 12 pages cover
-- ~24,000 features. No envelope filter — the county-wide layer is filtered by
-- County LIKE '%Fresno%'.

SELECT
    feature.properties.OBJECTID::INTEGER AS objectid,
    feature.properties.County::VARCHAR AS county,
    feature.properties.Code::VARCHAR AS code,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://gis.conservation.ca.gov/server/rest/services/DLRP/CaliforniaImportantFarmland_mostrecent/FeatureServer/0/query',
        'County LIKE ''%Fresno%''',
        'OBJECTID,County,Code',
        geometry = NULL,
        pages = 12
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
