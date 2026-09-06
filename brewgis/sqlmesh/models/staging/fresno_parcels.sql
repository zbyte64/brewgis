MODEL (
  name duckdb.staging.fresno_parcels,
  kind VIEW,
  gateway duckdb,
  dialect duckdb,
  columns (
    parcel_id VARCHAR,
    apn VARCHAR,
    agency_cod VARCHAR,
    roll_year VARCHAR,
    shape_area DOUBLE,
    geometry GEOMETRY
  )
);

-- Fresno Parcels — DuckDB VIEW that fetches and parses every page of the
-- Fresno County parcel ArcGIS FeatureServer via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (crs EPSG:4326, honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses
-- at 2000 records/request, so @fresno_parcel_page_urls emits paginated URLs
-- (step 2000) as a constant list_value(...) literal — DuckDB does not
-- accept subqueries or lateral columns inside table functions, so the page
-- list cannot be read from another relation. The page count is derived from
-- the service's live count each render (falling back to a fixed ceiling), so
-- the fetch scales if the parcel set changes.
--
-- Whitespace-only APN rows (3 degenerate zero-area features in the source)
-- are dropped: parcel_id = APN is the stable parcel key consumed by
-- parcel_shim, and rows without an APN are not identifiable parcels.

SELECT
    feature.properties.APN::VARCHAR AS parcel_id,
    feature.properties.APN::VARCHAR AS apn,
    feature.properties.AGENCY_COD::VARCHAR AS agency_cod,
    feature.properties.ROLL_YEAR::VARCHAR AS roll_year,
    feature.properties.SHAPE_AREA::DOUBLE AS shape_area,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @fresno_parcel_page_urls(),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature)
WHERE length(trim(feature.properties.APN::VARCHAR)) > 0;
