MODEL (
  name duckdb.fresno.city_boundary,
  kind VIEW,
  description 'DuckDB staging VIEW fetching the Fresno City Limits FeatureServer boundary record.',
  column_descriptions (
    objectid = 'Feature ID (FID) from the FeatureServer feature properties.',
    agency_cod = 'AGENCY_COD agency code from the FeatureServer feature properties.',
    agency_nam = 'AGENCY_NAM agency name from the FeatureServer feature properties; the fetch keeps only Fresno.',
    geometry = 'Boundary geometry parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat).'
  ),
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
-- from another relation. The page count is declared by the call site, never
-- probed, so rendering this model never touches the network (see
-- @arcgis_page_urls). AGENCY_NAM = 'Fresno' selects exactly one boundary
-- (1 feature = 1 page when this was written, 2026-09-23), so one page is the
-- whole set; extra pages would come back empty.

SELECT
    feature.properties.FID::INTEGER AS objectid,
    feature.properties.AGENCY_COD::VARCHAR AS agency_cod,
    feature.properties.AGENCY_NAM::VARCHAR AS agency_nam,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services/Fresno_City_Limits/FeatureServer/0/query',
        'AGENCY_NAM = ''Fresno''',
        'FID,AGENCY_COD,AGENCY_NAM',
        geometry = NULL,
        pages = 1
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
