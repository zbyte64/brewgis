MODEL (
  name duckdb.fresno.assessor_parcels,
  kind VIEW,
  description 'DuckDB staging VIEW fetching every page of the Fresno County assessor roll MapServer (FC_PARCEL_SELECT).',
  column_descriptions (
    apn = 'Assessor parcel number (APN) from the MapServer feature properties, trimmed to non-empty values.',
    use_primary = 'USE_PRIMARY assessor land-use code of the parcel (e.g. S01, A99, ALM).',
    use_secondary = 'USE_SECONDARY assessor land-use code of the parcel.',
    use_high_best = 'USE_HIGH_BEST assessor highest-and-best-use code of the parcel.',
    lot_size_acres = 'LOT_AREA assessor lot size in acres (source units).',
    assess_land_val = 'ASSESS_LAND_VAL assessed land value of the parcel (dollars).',
    assess_imp_val = 'ASSESS_IMP_VAL assessed improvement value of the parcel (dollars).',
    total_assessed_value = 'TOTAL_ASSESSED_VALUE total assessed value of the parcel (dollars).',
    tax_area_code = 'TAX_AREA_CODE county tax-area code of the parcel.',
    geometry = 'Feature geometry parsed from the page GeoJSON with ST_GeomFromGeoJSON (EPSG:4326 lon/lat).'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    apn VARCHAR,
    use_primary VARCHAR,
    use_secondary VARCHAR,
    use_high_best VARCHAR,
    lot_size_acres DOUBLE,
    assess_land_val DOUBLE,
    assess_imp_val DOUBLE,
    total_assessed_value DOUBLE,
    tax_area_code VARCHAR,
    geometry GEOMETRY
  )
);

-- Fresno Assessor Parcels — DuckDB VIEW fetching and parsing every page of the
-- Fresno County assessor roll MapServer (FC_PARCEL_SELECT) via read_json_auto.
--
-- Each page is a GeoJSON FeatureCollection (crs EPSG:4326, honored by
-- ST_GeomFromGeoJSON on each feature geometry). The service caps responses
-- at 2000 records/request, so @arcgis_page_urls emits paginated URLs
-- (step 2000) as a constant list_value(...) literal — DuckDB does not accept
-- subqueries or lateral columns inside table functions, so the page list
-- cannot be read from another relation. orderByFields=OBJECTID makes
-- resultOffset paging deterministic (the MapServer gives no stable row order
-- otherwise). The page count is declared by the call site, never probed, so
-- rendering this model never touches the network (see @arcgis_page_urls).
--
-- The envelope is the Fresno region bounding box (the same box fresno.parcels
-- and the Overture fresno blueprints use), so this roll spans the same area as
-- every other fresno source. The roll had 340,005 features in-bbox = 171 pages
-- when this was written (2026-09-23); pages = 216 covers ~432k features, and
-- _MAX_PAGE_COUNT was raised to 256 to stay above that. Extra pages come back
-- empty; too few pages truncate the roll silently, so raise `pages` when the
-- roll outgrows 432k features.
--
-- Grain is one row per situs-address feature (a parcel with several addresses
-- appears more than once); the assessor adapter collapses to one row per APN.
-- Rows without an APN are not identifiable parcels and are dropped.

SELECT
    feature.properties.APN::VARCHAR AS apn,
    feature.properties.USE_PRIMARY::VARCHAR AS use_primary,
    feature.properties.USE_SECONDARY::VARCHAR AS use_secondary,
    feature.properties.USE_HIGH_BEST::VARCHAR AS use_high_best,
    feature.properties.LOT_AREA::DOUBLE AS lot_size_acres,
    feature.properties.ASSESS_LAND_VAL::DOUBLE AS assess_land_val,
    feature.properties.ASSESS_IMP_VAL::DOUBLE AS assess_imp_val,
    feature.properties.TOTAL_ASSESSED_VALUE::DOUBLE AS total_assessed_value,
    feature.properties.TAX_AREA_CODE::VARCHAR AS tax_area_code,
    ST_GeomFromGeoJSON(to_json(feature.geometry)) AS geometry
FROM read_json_auto(
    @arcgis_page_urls(
        'https://gisprod10.co.fresno.ca.us/server/rest/services/FC_PARCEL_SELECT/MapServer/0/query',
        '1=1',
        'APN,USE_PRIMARY,USE_SECONDARY,USE_HIGH_BEST,LOT_AREA,ASSESS_LAND_VAL,ASSESS_IMP_VAL,TOTAL_ASSESSED_VALUE,TAX_AREA_CODE',
        geometry = '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        pages = 216,
        order_by = 'OBJECTID'
    ),
    format = 'auto'
) r,
UNNEST(r.features) AS t(feature)
WHERE length(trim(feature.properties.APN::VARCHAR)) > 0;
