MODEL (
  name duckdb.fresno.floodplains,
  kind VIEW,
  description 'DuckDB staging VIEW fetching FEMA NFHL MapServer layer 28 flood zone pages for Fresno.',
  column_descriptions (
    fld_zone = 'FLD_ZONE flood hazard zone code from the MapServer feature properties.',
    sfha_tf = 'SFHA_TF Special Flood Hazard Area flag from the MapServer feature properties.',
    static_bfe = 'STATIC_BFE static base flood elevation from the MapServer feature properties (source units).',
    geometry = 'Flood zone polygon parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat).'
  ),
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
-- from another relation. The page count is declared by the call site, never
-- probed, so rendering this model never touches the network (see
-- @arcgis_page_urls). The NFHL zone set had 656 features in-bbox = 1 page when
-- this was written (2026-09-23); the declared 4 pages cover ~8,000 polygons.
-- Empty tail pages simply yield zero rows.
--
-- The envelope is the Fresno region bounding box (matching fresno.parcels) so
-- the constraint layer covers every parcel in the base canvas — floodplains
-- feed the env_constraint analysis, which discounts developable area, so a
-- narrower envelope would silently exempt the uncovered parcels.

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
        geometry = '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        pages = 4
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature);
