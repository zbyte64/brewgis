MODEL (
  name duckdb.fresno.assessor_parcels,
  kind VIEW,
  description 'DuckDB staging VIEW reading the Fresno County assessor roll MapServer (FC_PARCEL_SELECT) through arcgis_query.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) from the MapServer APN field, trimmed to non-empty values.',
    use_primary = 'USE_PRIMARY assessor land-use code of the parcel (e.g. S01, A99, ALM).',
    use_secondary = 'USE_SECONDARY assessor land-use code of the parcel.',
    use_high_best = 'USE_HIGH_BEST assessor highest-and-best-use code of the parcel.',
    lot_size_acres = 'LOT_AREA assessor lot size in acres (source units).',
    assess_land_val = 'ASSESS_LAND_VAL assessed land value of the parcel (dollars).',
    assess_imp_val = 'ASSESS_IMP_VAL assessed improvement value of the parcel (dollars).',
    total_assessed_value = 'TOTAL_ASSESSED_VALUE total assessed value of the parcel (dollars).',
    tax_area_code = 'TAX_AREA_CODE county tax-area code of the parcel.',
    geometry = 'Parcel polygon returned by arcgis_query in EPSG:4326 lon/lat.'
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

-- Fresno Assessor Parcels — DuckDB VIEW over the Fresno County assessor roll
-- MapServer (FC_PARCEL_SELECT). arcgis_query (the arcgis extension) pages
-- through the whole layer — ordered by its object id, so the pages neither
-- overlap nor skip features — and returns its fields as typed columns plus an
-- EPSG:4326 geometry. The roll had 340,005 features in-bbox when this was
-- written (2026-09-23).
--
-- The envelope is the Fresno region bounding box (the same box fresno.parcels
-- and the Overture fresno blueprints use), so this roll spans the same area as
-- every other fresno source. inSR declares the envelope lon/lat: the layer is
-- projected (SR 2228), and without it the server reads the envelope in that SR
-- and returns zero features.
--
-- Grain is one row per situs-address feature (a parcel with several addresses
-- appears more than once); the assessor adapter collapses to one row per APN.
-- Rows without an APN are not identifiable parcels and are dropped.

SELECT
    APN AS apn,
    USE_PRIMARY AS use_primary,
    USE_SECONDARY AS use_secondary,
    USE_HIGH_BEST AS use_high_best,
    LOT_AREA::DOUBLE AS lot_size_acres,
    ASSESS_LAND_VAL::DOUBLE AS assess_land_val,
    ASSESS_IMP_VAL::DOUBLE AS assess_imp_val,
    TOTAL_ASSESSED_VALUE::DOUBLE AS total_assessed_value,
    TAX_AREA_CODE AS tax_area_code,
    geometry
FROM arcgis_query(
    'https://gisprod10.co.fresno.ca.us/server/rest/services/FC_PARCEL_SELECT/MapServer/0',
    query_params := MAP {
        'geometry': '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
)
WHERE length(trim(APN)) > 0;
