MODEL (
  name duckdb.staging.fresno_farmland,
  kind VIEW,
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
-- from another relation. The page count is derived from the service's live
-- count each render (falling back to a fixed ceiling of 12 pages ≈ 24,000
-- features), so the fetch scales if the farmland set changes. No envelope
-- filter — the county-wide layer is filtered by County LIKE '%Fresno%'.

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
        fallback_pages = 12
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
