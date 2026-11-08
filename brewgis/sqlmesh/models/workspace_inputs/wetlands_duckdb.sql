MODEL (
  name duckdb.@{workspace_schema}.wetlands,
  kind VIEW,
  description 'DuckDB staging VIEW reading the CA Fish and Wildlife NWI wetland FeatureServer over the workspace extent through arcgis_query.',
  column_descriptions (
    attribute = 'ATTRIBUTE NWI Cowardin classification code from the FeatureServer (e.g. PEM1C).',
    wetland_type = 'WETLAND_TYPE wetland label from the NWI FeatureServer; the fetch keeps the Freshwater classes.',
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
  ),
  blueprints @workspace_blueprints('public_constraints')
);

-- Freshwater wetlands over the workspace extent — DuckDB VIEW over the CA Dept
-- of Fish & Wildlife BIOS NWI FeatureServer (statewide: an extent outside
-- California finds no wetlands here), one instance per workspace with public
-- constraints. arcgis_query (the arcgis extension) pages through every feature
-- matching the server-side where clause and envelope and returns the layer's
-- fields as typed columns plus an EPSG:4326 geometry.
--
-- The filter is on WETLAND_TYPE, the NWI class label ('Freshwater Emergent
-- Wetland', 'Freshwater Forested/Shrub Wetland', 'Freshwater Pond'; the other
-- labels are 'Lake' and 'Riverine'). ATTRIBUTE is the NWI Cowardin code
-- ('PEM1C', 'PABFh', …), which never contains the word, so the earlier
-- ATTRIBUTE LIKE '%Fresh%' filter matched nothing: 0 features against 783
-- freshwater ones in the Fresno envelope (2026-10-18). SACOG's envelope holds
-- 19,631 (2026-10-19).
--
-- The envelope is the workspace extent, as for the floodplains.

SELECT
    ATTRIBUTE AS attribute,
    WETLAND_TYPE AS wetland_type,
    ACRES AS acres,
    geometry
FROM arcgis_query(
    'https://services2.arcgis.com/Uq9r85Potqm3MfRV/ArcGIS/rest/services/biosds2630_fpu/FeatureServer/0',
    where_clause := 'WETLAND_TYPE LIKE ''Freshwater%''',
    query_params := MAP {
        'geometry': @arcgis_envelope(
            @extent_min_x,
            @extent_min_y,
            @extent_max_x,
            @extent_max_y
        ),
        'geometryType': 'esriGeometryEnvelope',
        'inSR': '4326',
        'spatialRel': 'esriSpatialRelIntersects'
    }
);
