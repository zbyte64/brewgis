MODEL (
  name duckdb.fresno.parcels,
  kind VIEW,
  description 'DuckDB staging VIEW fetching every page of the Fresno County parcel FeatureServer.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) from the FeatureServer feature properties, trimmed to non-empty values.',
    apn = 'Assessor parcel number (APN) from the FeatureServer feature properties; same value as parcel_id.',
    agency_cod = 'AGENCY_COD agency code from the FeatureServer feature properties.',
    roll_year = 'ROLL_YEAR assessor roll year from the FeatureServer feature properties.',
    shape_area = 'SHAPE_AREA attribute from the FeatureServer feature properties (source units).',
    geometry = 'Feature geometry parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat).'
  ),
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
-- at 2000 records/request, so @arcgis_page_urls emits paginated URLs
-- (step 2000) as a constant list_value(...) literal — DuckDB does not
-- accept subqueries or lateral columns inside table functions, so the page
-- list cannot be read from another relation. The page count is declared by the
-- call site, never probed, so rendering this model never touches the network
-- (see @arcgis_page_urls). The parcel set had 213,145 features in-bbox = 107
-- pages when this was written (2026-09-23); pages = 136 covers ~272k features.
--
-- The envelope is the Fresno region bounding box, and it MUST contain the
-- whole City of Fresno: parcel_shim consumes this model verbatim (no spatial
-- filter) and every fresno base-canvas model is keyed off that parcel set.
-- It matches the Overture fresno blueprint box (overture_buildings /
-- overture_transport / overture_land_use / overture_land_cover) so all fresno
-- sources span the same area. The City Limits service
-- (Fresno_City_Limits/FeatureServer, AGENCY_NAM = 'Fresno') spans
-- -119.9344..-119.6505 lon, 36.6627..36.9110 lat; the previous
-- -119.82,36.72,-119.72,36.80 envelope covered only 24% of the city area.
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
    @arcgis_page_urls(
        'https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services/Fresno_County_Parcels/FeatureServer/0/query',
        '1=1',
        'APN,AGENCY_COD,ROLL_YEAR,SHAPE_AREA',
        geometry = '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        pages = 136
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature)
WHERE length(trim(feature.properties.APN::VARCHAR)) > 0;
