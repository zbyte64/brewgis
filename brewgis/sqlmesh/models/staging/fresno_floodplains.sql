MODEL (
  name duckdb.staging.fresno_floodplains,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    fld_zone VARCHAR,
    sfha_tf VARCHAR,
    static_bfe DOUBLE,
    geometry GEOMETRY
  )
);

-- FEMA NFHL flood zones (Fresno County area) — DuckDB VIEW that fetches and
-- parses every page of the FEMA National Flood Hazard Layer MapServer via
-- read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (RFC 7946, EPSG:4326 — honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses at
-- 2000 records/request, so @arcgis_page_urls emits paginated URLs (step 2000)
-- as a constant list_value(...) literal — DuckDB does not accept subqueries
-- or lateral columns inside table functions, so the page list cannot be read
-- from another relation. The page count is derived from the service's live
-- count each render (falling back to a fixed ceiling), so the fetch scales if
-- the flood zone set changes. Empty tail pages simply yield zero rows.

SELECT
    feature.properties.FLD_ZONE::VARCHAR AS fld_zone,
    feature.properties.SFHA_TF::VARCHAR AS sfha_tf,
    feature.properties.STATIC_BFE::DOUBLE AS static_bfe,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query',
        '1=1',
        'FLD_ZONE,SFHA_TF,STATIC_BFE',
        geometry = '{"xmin":-119.82,"ymin":36.72,"xmax":-119.72,"ymax":36.80}'
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
