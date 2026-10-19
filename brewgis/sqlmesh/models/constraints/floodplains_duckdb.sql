MODEL (
  name duckdb.@{region}.floodplains,
  kind VIEW,
  description 'DuckDB staging VIEW reading FEMA NFHL MapServer layer 28 Special Flood Hazard Area zones over the region bounding box through arcgis_query.',
  column_descriptions (
    fld_zone = 'FLD_ZONE flood hazard zone code from the MapServer.',
    sfha_tf = 'SFHA_TF Special Flood Hazard Area flag from the MapServer; always T (the fetch keeps only the SFHA).',
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
  ),
  blueprints @region_blueprints()
);

-- FEMA NFHL Special Flood Hazard Areas over the region — DuckDB VIEW over the
-- FEMA National Flood Hazard Layer MapServer, one instance per region data
-- pipeline. arcgis_query (the arcgis extension) pages through every feature
-- matching the where clause in the envelope and returns the layer's fields as
-- typed columns plus an EPSG:4326 geometry.
--
-- Only the SFHA (SFHA_TF = 'T': zones A, AE, AH, AO, V, VE — the 1 % annual-
-- chance flood) is fetched, server-side. It is the only part a constraint
-- reads (constraints/constraint_layers.sql), and the rest cannot be fetched:
-- Zone X (minimal hazard) is the remainder of the mapped area in a handful of
-- enormous polygons (Fresno: 10,713 km2, one polygon 9,168 km2), and over the
-- SACOG envelope a 1,000-feature page of all zones took 78 s and the
-- extension's 2,000-feature pages failed with "ArcGIS server returned an
-- error (code 500)". SFHA features in the envelope (2026-10-19): SACOG 2,674 of
-- 7,250; Fresno 369 of 656.
--
-- The envelope is the region's Overture bounding box (the window its parcels
-- are built from) so the layer covers every parcel of the region's base
-- canvas: floodplains feed the env_constraint analysis through
-- constraints/constraint_layers.sql, so a narrower envelope would silently
-- exempt the uncovered parcels.

SELECT
    FLD_ZONE AS fld_zone,
    SFHA_TF AS sfha_tf,
    STATIC_BFE AS static_bfe,
    geometry
FROM arcgis_query(
    'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28',
    where_clause := 'SFHA_TF = ''T''',
    query_params := MAP {
        'geometry': @arcgis_envelope(
            @overture_bbox_min_x,
            @overture_bbox_min_y,
            @overture_bbox_max_x,
            @overture_bbox_max_y
        ),
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
);
