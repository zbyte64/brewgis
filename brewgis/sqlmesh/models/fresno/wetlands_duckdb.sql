MODEL (
  name duckdb.fresno.wetlands,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CA Fish and Wildlife NWI wetland FeatureServer through arcgis_query.',
  column_descriptions (
    attribute = 'ATTRIBUTE classification from the NWI FeatureServer; the fetch keeps Fresh values.',
    wetland_type = 'WETLAND_TYPE wetland label from the NWI FeatureServer.',
    acres = 'ACRES attribute from the NWI FeatureServer (acres, as published by the source).',
    geometry = 'Wetland polygon returned by arcgis_query in EPSG:4326 lon/lat.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    attribute VARCHAR,
    wetland_type VARCHAR,
    acres DOUBLE,
    geometry GEOMETRY
  )
);

-- Freshwater wetlands (Fresno County area) — DuckDB VIEW over the CA Dept of
-- Fish & Wildlife BIOS NWI FeatureServer. arcgis_query (the arcgis extension)
-- pages through every feature matching the server-side where clause and
-- envelope and returns the layer's fields as typed columns plus an EPSG:4326
-- geometry. The ATTRIBUTE LIKE '%Fresh%' filter matches the legacy
-- fresno_downloader query; it legitimately yields zero features for the fresno
-- region envelope (0 features when this was written, 2026-09-23, verified
-- against both the previous downtown box and the current region box), so the
-- table may be empty.
--
-- The envelope is the Fresno region bounding box (matching fresno.parcels)
-- so the constraint layer covers every parcel in the base canvas.

SELECT
    ATTRIBUTE AS attribute,
    WETLAND_TYPE AS wetland_type,
    ACRES AS acres,
    geometry
FROM arcgis_query(
    'https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/biosds2630_fpu/FeatureServer/0',
    where_clause := 'ATTRIBUTE LIKE ''%Fresh%''',
    query_params := MAP {
        'geometry': '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
);
