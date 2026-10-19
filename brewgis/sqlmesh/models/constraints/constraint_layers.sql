MODEL (
  name brewgis.@{region}.constraint_layers,
  kind FULL,
  description 'Environmental constraint polygons for the region from public data (FEMA Special Flood Hazard Areas and NWI freshwater wetlands), subdivided, with the share of each overlap that comes off developable acreage.',
  column_descriptions (
    layer = 'Constraint layer the polygon comes from: floodplains or wetlands.',
    discount_pct = 'Share of the overlapping parcel area excluded from developable acreage (percent, 0-100).',
    geom = 'Constraint polygon piece (ST_Subdivide, at most 256 vertices) at SRID 4326.',
    local_geom = 'The same piece in the project local_srid, made valid there (projection can fold a sliver into a self-intersection); env_constraint measures overlaps on it.'
  ),
  columns (
    layer TEXT,
    discount_pct DOUBLE PRECISION,
    geom GEOMETRY(POLYGON, 4326),
    local_geom GEOMETRY
  ),
  blueprints @region_blueprints()
);

-- Region constraint layers — what env_constraint discounts for a workspace on
-- a region data pipeline's reconstructed base canvas. env_constraint reads its
-- analysis region's model (``brewgis.@{region}.constraint_layers``, the region
-- coming from the workspace's base table — see macros/analysis_blueprints.py),
-- so the layers a region constrains are decided in SQL and a scenario sets
-- none. A reconstruction is built from public data and is analyzed against
-- public data; the imported SACOG snapshot has its own model
-- (sacog_v1/constraint_layers.sql) over the layers it shipped with.
--
--   * floodplains: the FEMA NFHL Special Flood Hazard Area (zones A, AE, AH,
--     AO, V, VE; the 1 % annual-chance flood) — all the fetch keeps
--     (constraints/floodplains_duckdb.sql). Zone X (minimal hazard) is the
--     rest of the mapped area: 10,713 km2 of it in the Fresno envelope against
--     105 km2 of SFHA. Counting it would mark nearly every parcel wholly
--     undevelopable.
--   * wetlands: every NWI freshwater wetland the fetch returns.
--
-- Both take the whole overlap (100 %), as UrbanFootprint's environmental
-- constraint module does for its layers.
--
-- The polygons are subdivided so env_constraint's per-polygon index probe
-- against the parcels covers a small box instead of a county-sized one;
-- env_constraint unions the pieces per parcel, so the split never changes an
-- overlap's area. ST_MakeValid + ST_CollectionExtract keep only the polygonal
-- part of a repaired ring.

WITH src AS (
    SELECT 'floodplains'::text AS layer, 100.0::double precision AS discount_pct, geom
    FROM brewgis.@{region}.floodplains
    UNION ALL
    SELECT 'wetlands'::text AS layer, 100.0::double precision AS discount_pct, geom
    FROM brewgis.@{region}.wetlands
),

pieces AS (
    SELECT
        layer,
        discount_pct,
        ST_Subdivide(ST_CollectionExtract(ST_MakeValid(geom), 3), 256) AS geom
    FROM src
    WHERE geom IS NOT NULL
)

SELECT
    layer,
    discount_pct,
    geom,
    -- Valid in 4326 is not valid in local_srid: projecting a subdivided sliver
    -- can fold it into a self-intersection (20 of SACOG's 38,198 pieces), which
    -- GEOS's ST_Intersection refuses ("TopologyException: side location
    -- conflict"). Made valid once here rather than per parcel in env_constraint.
    ST_CollectionExtract(ST_MakeValid(ST_Transform(geom, @local_srid())), 3) AS local_geom
FROM pieces;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_constraint_layers_geom_')
  ON @this_model USING GIST (geom);
ANALYZE @this_model;
