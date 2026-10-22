MODEL (
  name brewgis.@{workspace_schema}.constraint_layers,
  kind FULL,
  description 'Environmental constraint polygons of the workspace (public FEMA flood zones and NWI wetlands over its extent, or the layers its package shipped), subdivided, with the share of each overlap that comes off developable acreage.',
  column_descriptions (
    layer = 'Constraint layer the polygon comes from (floodplains or wetlands for public data; the package''s own layer names otherwise).',
    discount_pct = 'Share of the overlapping parcel area excluded from developable acreage (percent, 0-100).',
    geom = 'Constraint polygon piece (ST_Subdivide, at most 256 vertices) at SRID 4326.',
    local_geom = 'The same piece in the workspace CRS (Workspace.local_srid), made valid there (projection can fold a sliver into a self-intersection); env_constraint measures overlaps on it.'
  ),
  columns (
    layer TEXT,
    discount_pct DOUBLE PRECISION,
    geom GEOMETRY(POLYGON, 4326),
    local_geom GEOMETRY
  ),
  blueprints @workspace_blueprints()
);

-- Workspace constraint layers — what env_constraint discounts
-- (``brewgis.@{workspace_schema}.constraint_layers``, see
-- macros/workspace_blueprints.py), so the layers a workspace constrains are
-- decided in SQL and a scenario sets none. Where the polygons come from is the
-- workspace's ``constraint_source``, resolved to the input model this reads
-- (``constraint_input``):
--
--   * ``public`` — workspace_inputs/constraints_public.sql: FEMA Special
--     Flood Hazard Areas and NWI freshwater wetlands fetched over the extent;
--   * ``package`` — workspace_inputs/constraints_package_raw.sql: the layers
--     the workspace's package shipped, each with its own discount (e.g. the
--     SACOG v1 snapshot's streams, wetlands and vernal pools).
--
-- One model reads either source rather than one model per source, so a model
-- name is only ever declared by one file (SQLMesh caches a file's blueprint
-- expansion by its mtime, so two files declaring one name per source would
-- collide the moment a workspace's source changes).
--
-- The polygons are subdivided so env_constraint's per-polygon index probe
-- against the parcels covers a small box instead of a county-sized one;
-- env_constraint unions the pieces per parcel, so the split never changes an
-- overlap's area. ST_MakeValid + ST_CollectionExtract keep only the polygonal
-- part of a repaired ring. A package exported from another workspace ships its
-- pieces already subdivided, and re-subdividing a piece of at most 256 vertices
-- returns it unchanged. ``ST_SetSRID`` re-tags the package bridge's SRID-less
-- geometry (DuckDB-to-PostGIS transfers write SRID 0) and is a no-op on the
-- public layers' EPSG:4326.

WITH pieces AS (
    SELECT
        layer,
        discount_pct,
        ST_Subdivide(
            ST_CollectionExtract(ST_MakeValid(ST_SetSRID(geom, 4326)), 3),
            256
        ) AS geom
    FROM brewgis.@{workspace_schema}.@{constraint_input}
    WHERE geom IS NOT NULL
)

SELECT
    layer,
    discount_pct,
    geom,
    -- Valid in 4326 is not valid in the workspace CRS: projecting a subdivided
    -- sliver can fold it into a self-intersection (20 of SACOG's 38,198
    -- pieces), which GEOS's ST_Intersection refuses ("TopologyException: side
    -- location conflict"). Made valid once here rather than per parcel in
    -- env_constraint.
    ST_CollectionExtract(ST_MakeValid(ST_Transform(geom, @workspace_srid())), 3) AS local_geom
FROM pieces;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_constraint_layers_geom_')
  ON @this_model USING GIST (geom);
ANALYZE @this_model;
