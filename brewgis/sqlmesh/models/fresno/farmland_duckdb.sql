MODEL (
  name duckdb.fresno.farmland,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CA Important Farmland FeatureServer for Fresno County through arcgis_query.',
  column_descriptions (
    objectid = 'OBJECTID of the farmland polygon from the FeatureServer.',
    county = 'County name (County) from the FeatureServer; the fetch keeps Fresno.',
    code = 'Important Farmland class code (Code) from the FeatureServer.',
    geometry = 'Farmland polygon returned by arcgis_query in EPSG:4326 lon/lat.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    objectid INTEGER,
    county VARCHAR,
    code VARCHAR,
    geometry GEOMETRY
  )
);

-- California Important Farmland (Fresno County) — DuckDB VIEW over the CA Dept
-- of Conservation Important Farmland FeatureServer. arcgis_query (the arcgis
-- extension) pages through every feature matching the server-side where
-- clause and returns the layer's fields as typed columns plus an EPSG:4326
-- geometry. The county-wide farmland set had 10,495 features when this was
-- written (2026-09-23). No envelope filter — the county-wide layer is filtered
-- by County LIKE '%Fresno%'.

SELECT
    OBJECTID::INTEGER AS objectid,
    County AS county,
    Code AS code,
    geometry
FROM arcgis_query(
    'https://gis.conservation.ca.gov/server/rest/services/DLRP/CaliforniaImportantFarmland_mostrecent/FeatureServer/0',
    where_clause := 'County LIKE ''%Fresno%'''
);
