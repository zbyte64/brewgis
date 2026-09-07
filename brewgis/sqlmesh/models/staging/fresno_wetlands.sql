MODEL (
  name duckdb.staging.fresno_wetlands,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    attribute VARCHAR,
    wetland_type VARCHAR,
    acres DOUBLE,
    geometry GEOMETRY
  )
);

-- Freshwater wetlands (Fresno County area) — DuckDB VIEW that fetches and
-- parses every page of the CA Dept of Fish & Wildlife BIOS NWI FeatureServer
-- via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000)
-- as a constant list_value(...) literal — DuckDB does not accept subqueries
-- or lateral columns inside table functions, so the page list cannot be read
-- from another relation. The page count is derived from the service's live
-- count each render (falling back to a fixed ceiling), so the fetch scales if
-- the wetland set changes. The ATTRIBUTE LIKE '%Fresh%' filter matches the
-- legacy fresno_downloader query; it legitimately yields zero features for
-- this envelope (verified), so the table may be empty.

SELECT
    feature.properties.ATTRIBUTE::VARCHAR AS attribute,
    feature.properties.WETLAND_TYPE::VARCHAR AS wetland_type,
    feature.properties.ACRES::DOUBLE AS acres,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/biosds2630_fpu/FeatureServer/0/query',
        'ATTRIBUTE LIKE ''%Fresh%''',
        'ATTRIBUTE,WETLAND_TYPE,ACRES',
        geometry = '{"xmin":-119.82,"ymin":36.72,"xmax":-119.72,"ymax":36.80}'
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
