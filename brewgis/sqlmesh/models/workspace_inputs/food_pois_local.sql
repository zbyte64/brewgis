MODEL (
  name brewgis.@{workspace_schema}.food_pois_local,
  kind FULL,
  description 'Workspace food outlets projected to the workspace CRS with healthy/unhealthy flags and a GiST index: the search input the per-scenario food-access mRFEI counts against.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag carried through from the workspace''s outlets.',
    shop = 'Element shop tag value carried through from the workspace''s outlets.',
    amenity = 'Element amenity tag value carried through from the workspace''s outlets.',
    is_healthy = 'True for a grocery outlet (supermarket, grocery, grocer or farmers market).',
    is_unhealthy = 'True for a convenience store or fast-food outlet.',
    geometry = 'Outlet point projected into the workspace CRS (Workspace.local_srid), with a GiST index for the 1 km searches the analysis runs against it.'
  ),
  audits (
    not_null(columns := (osm_id,)),
    -- A fetch that returned nothing (Overpass down, or a bbox that matched no
    -- element) fails the plan here rather than silently reporting every parcel
    -- as having no outlet within reach.
    assert_row_count_greater_than_zero
  ),
  dialect postgres,
  blueprints @workspace_blueprints()
);

-- Food outlets in the workspace CRS, for ST_DWithin searches.
--
-- The projection happens here rather than in the DuckDB fetch because DuckDB's
-- ST_Transform to a projected CRS produces NaN/Infinity coordinates (see the
-- gateway linter's duckdbtransformwarning): the source is EPSG:4326 — the
-- bridge's SRID 0 is re-tagged by ``workspace_inputs/food_pois.sql``, the VIEW read here —
-- and this PostGIS model is the one that owns the projected geometry, its
-- index, and therefore the radius searches measured by
-- ``@metres_in_local_units``.

SELECT
    osm_id,
    name,
    shop,
    amenity,
    food_class = 'healthy' AS is_healthy,
    food_class = 'unhealthy' AS is_unhealthy,
    ST_Transform(geometry, @workspace_srid()) AS geometry
FROM brewgis.@{workspace_schema}.food_pois;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_food_pois_local_geometry_')
  ON @this_model USING GIST (geometry);
  ANALYZE @this_model;
