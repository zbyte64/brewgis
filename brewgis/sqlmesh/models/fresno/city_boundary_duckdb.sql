MODEL (
  name duckdb.fresno.city_boundary,
  kind VIEW,
  description 'DuckDB staging VIEW reading the Fresno City Limits FeatureServer boundary record through arcgis_query.',
  column_descriptions (
    objectid = 'Feature ID (FID) from the FeatureServer.',
    agency_cod = 'AGENCY_COD agency code from the FeatureServer.',
    agency_nam = 'AGENCY_NAM agency name from the FeatureServer; the fetch keeps only Fresno.',
    geometry = 'Boundary polygon returned by arcgis_query in EPSG:4326 lon/lat.'
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

-- City of Fresno boundary — DuckDB VIEW over the Fresno City Limits
-- FeatureServer. arcgis_query (the arcgis extension) returns the layer's
-- fields as typed columns plus an EPSG:4326 geometry; the server applies the
-- where clause. AGENCY_NAM = 'Fresno' selects exactly one boundary (1 feature
-- when this was written, 2026-09-23).

SELECT
    FID::INTEGER AS objectid,
    AGENCY_COD AS agency_cod,
    AGENCY_NAM AS agency_nam,
    geometry
FROM arcgis_query(
    'https://services6.arcgis.com/Gs01XZPFhKUG8tKU/ArcGIS/rest/services/Fresno_City_Limits/FeatureServer/0',
    where_clause := 'AGENCY_NAM = ''Fresno'''
);
