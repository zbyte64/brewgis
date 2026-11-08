MODEL (
  name brewgis.@{workspace_schema}.wetlands,
  kind VIEW,
  description 'NWI freshwater wetlands over the workspace extent from the CA Fish and Wildlife BIOS service.',
  column_descriptions (
    attribute = 'ATTRIBUTE NWI Cowardin classification code of the record (e.g. PEM1C).',
    wetland_type = 'WETLAND_TYPE wetland label of the polygon; the fetch keeps the Freshwater classes.',
    acres = 'ACRES attribute of the wetland polygon as published by the source service (acres).',
    geom = 'Wetland polygon at SRID 4326, restored with ST_SetSRID from the bridge table geometry.'
  ),
  columns (
    attribute TEXT,
    wetland_type TEXT,
    acres DOUBLE PRECISION,
    geom GEOMETRY(GEOMETRY, 4326)
  ),
  blueprints @workspace_blueprints('public_constraints')
);

-- Workspace Wetlands — PostGIS VIEW wrapping the DuckDB bridge table with
-- proper SRID column metadata.
--
-- The DuckDB bridge (brewgis.<workspace_schema>.wetlands_raw) materializes the
-- fetched wetlands with ST_SetCRS, then SQLMesh exposes it to PostGIS via
-- FDW. The FDW drops SRID metadata, so all geometries arrive as SRID=0.
--
-- This VIEW restores SRID 4326 via ST_SetSRID and renames the geometry column
-- to geom; workspace_inputs/constraints_public.sql reads it.

SELECT
    attribute,
    wetland_type,
    acres,
    ST_SetSRID(geometry, 4326) AS geom
FROM brewgis.@{workspace_schema}.wetlands_raw;
