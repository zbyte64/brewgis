MODEL (
  name duckdb.fresno.floodplains,
  kind VIEW,
  description 'DuckDB staging VIEW reading FEMA NFHL MapServer layer 28 flood zones for Fresno through arcgis_query.',
  column_descriptions (
    fld_zone = 'FLD_ZONE flood hazard zone code from the MapServer.',
    sfha_tf = 'SFHA_TF Special Flood Hazard Area flag from the MapServer.',
    static_bfe = 'STATIC_BFE static base flood elevation from the MapServer (source units).',
    geometry = 'Flood zone polygon returned by arcgis_query in EPSG:4326 lon/lat.'
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

-- FEMA NFHL flood zones (Fresno County area) — DuckDB VIEW over the FEMA
-- National Flood Hazard Layer MapServer. arcgis_query (the arcgis extension)
-- pages through every feature in the envelope and returns the layer's fields
-- as typed columns plus an EPSG:4326 geometry. The NFHL zone set had 656
-- features in-bbox when this was written (2026-09-23).
--
-- The envelope is the Fresno region bounding box (matching fresno.parcels) so
-- the constraint layer covers every parcel in the base canvas — floodplains
-- feed the env_constraint analysis, which discounts developable area, so a
-- narrower envelope would silently exempt the uncovered parcels.

SELECT
    FLD_ZONE AS fld_zone,
    SFHA_TF AS sfha_tf,
    STATIC_BFE AS static_bfe,
    geometry
FROM arcgis_query(
    'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28',
    query_params := MAP {
        'geometry': '{"xmin":-119.95,"ymin":36.60,"xmax":-119.55,"ymax":36.92}',
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
);
