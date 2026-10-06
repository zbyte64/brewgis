MODEL (
  name duckdb.fresno.parcels,
  kind VIEW,
  description 'DuckDB staging VIEW reading the Fresno County parcel FeatureServer through arcgis_query.',
  column_descriptions (
    parcel_id = 'Assessor parcel number (APN) from the FeatureServer APN field, trimmed to non-empty values.',
    apn = 'Assessor parcel number (APN) from the FeatureServer APN field; same value as parcel_id.',
    agency_cod = 'AGENCY_COD agency code from the FeatureServer.',
    roll_year = 'ROLL_YEAR assessor roll year from the FeatureServer.',
    shape_area = 'SHAPE_AREA attribute from the FeatureServer (source units).',
    geometry = 'Parcel polygon returned by arcgis_query in EPSG:4326 lon/lat.'
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

-- Fresno Parcels — DuckDB VIEW over the Fresno County parcel ArcGIS
-- FeatureServer. arcgis_query (the arcgis extension) pages through the whole
-- layer and returns its fields as typed columns plus an EPSG:4326 geometry.
-- The parcel set had 213,145 features in-bbox when this was written
-- (2026-09-23).
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
-- inSR declares the envelope lon/lat; the server filters with it.
--
-- Whitespace-only APN rows (3 degenerate zero-area features in the source)
-- are dropped: parcel_id = APN is the stable parcel key consumed by
-- parcel_shim, and rows without an APN are not identifiable parcels.

SELECT
    APN AS parcel_id,
    APN AS apn,
    AGENCY_COD AS agency_cod,
    ROLL_YEAR AS roll_year,
    SHAPE_AREA AS shape_area,
    geometry
FROM arcgis_query(
    'https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services/Fresno_County_Parcels/FeatureServer/0',
    query_params := MAP {
        'geometry': '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
)
WHERE length(trim(APN)) > 0;
