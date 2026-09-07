MODEL (
  name duckdb.staging.fresno_city_boundary,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    objectid INTEGER,
    agency_cod VARCHAR,
    agency_nam VARCHAR,
    geometry GEOMETRY
  )
);

-- City of Fresno boundary — DuckDB VIEW that fetches the Fresno City Limits
-- FeatureServer via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000)
-- as a constant list_value(...) literal — DuckDB does not accept subqueries
-- or lateral columns inside table functions, so the page list cannot be read
-- from another relation. The page count is derived from the service's live
-- count each render (falling back to a fixed ceiling), so the fetch scales if
-- the boundary set changes. No envelope filter — the single city boundary is
-- selected by AGENCY_NAM = 'Fresno'.

SELECT
    feature.properties.FID::INTEGER AS objectid,
    feature.properties.AGENCY_COD::VARCHAR AS agency_cod,
    feature.properties.AGENCY_NAM::VARCHAR AS agency_nam,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services/Fresno_City_Limits/FeatureServer/0/query',
        'AGENCY_NAM = ''Fresno''',
        'FID,AGENCY_COD,AGENCY_NAM'
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
