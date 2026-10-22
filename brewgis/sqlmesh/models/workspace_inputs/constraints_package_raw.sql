MODEL (
  name brewgis.@{workspace_schema}.constraints_package_raw,
  kind FULL,
  description 'Environmental constraint polygons shipped in the workspace package, materialized in PostGIS by DuckDB, one polygon per row with the share of an overlap that comes off developable acreage.',
  column_descriptions (
    layer = 'Constraint layer the polygon comes from, as the package names it (e.g. streams, wetlands, vernal_pools).',
    discount_pct = 'Share of the overlapping parcel area excluded from developable acreage (percent, 0-100).',
    geom = 'Constraint polygon in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read the workspace''s constraint_layers model for the re-tagged, subdivided pieces.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    layer VARCHAR,
    discount_pct DOUBLE,
    geom GEOMETRY
  ),
  blueprints @workspace_blueprints('package_constraints')
);

-- Packaged constraint layers — the ``constraint_layers`` part of the package a
-- workspace was imported from (``Workspace.constraint_source = package``): the
-- layers that came with the base layer rather than the public FEMA/NWI ones,
-- e.g. the SACOG v1 snapshot's streams, wetlands and vernal pools. The package
-- names each layer and its discount; workspace_inputs/constraint_layers.sql
-- subdivides and projects them for env_constraint.
--
-- The part is a local GeoParquet file, read in the bridge itself: there is no
-- remote fetch for a staging VIEW to cache.

SELECT
    layer::VARCHAR AS layer,
    discount_pct::DOUBLE AS discount_pct,
    ST_SetCRS(geometry, 'EPSG:4326') AS geom
FROM read_parquet(@constraint_layers_parquet);
