MODEL (
  name brewgis.@{workspace_schema}.constraints_public,
  kind VIEW,
  description 'Public environmental constraint polygons over the workspace extent (FEMA Special Flood Hazard Areas and NWI freshwater wetlands), with the share of each overlap that comes off developable acreage.',
  column_descriptions (
    layer = 'Constraint layer the polygon comes from: floodplains or wetlands.',
    discount_pct = 'Share of the overlapping parcel area excluded from developable acreage (percent, 0-100).',
    geom = 'Constraint polygon at SRID 4326.'
  ),
  columns (
    layer TEXT,
    discount_pct DOUBLE PRECISION,
    geom GEOMETRY(GEOMETRY, 4326)
  ),
  blueprints @workspace_blueprints('public_constraints')
);

-- The public constraint layers of a workspace whose ``constraint_source`` is
-- ``public`` — workspace_inputs/constraint_layers.sql subdivides them for
-- env_constraint:
--
--   * floodplains: the FEMA NFHL Special Flood Hazard Area (zones A, AE, AH,
--     AO, V, VE; the 1 % annual-chance flood) — all the fetch keeps
--     (workspace_inputs/floodplains_duckdb.sql). Zone X (minimal hazard) is the
--     rest of the mapped area: 10,713 km2 of it in the Fresno envelope against
--     105 km2 of SFHA. Counting it would mark nearly every parcel wholly
--     undevelopable.
--   * wetlands: every NWI freshwater wetland the fetch returns.
--
-- Both take the whole overlap (100 %), as UrbanFootprint's environmental
-- constraint module does for its layers.

SELECT 'floodplains'::text AS layer, 100.0::double precision AS discount_pct, geom
FROM brewgis.@{workspace_schema}.floodplains
UNION ALL
SELECT 'wetlands'::text AS layer, 100.0::double precision AS discount_pct, geom
FROM brewgis.@{workspace_schema}.wetlands;
