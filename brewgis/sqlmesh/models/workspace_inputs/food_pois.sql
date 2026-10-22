MODEL (
  name brewgis.@{workspace_schema}.food_pois,
  kind VIEW,
  description 'PostGIS VIEW over the food-outlet bridge that restores SRID metadata with ST_SetSRID: the workspace''s food outlets, one point per OSM node or way.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag carried through from the workspace''s outlets.',
    shop = 'Element shop tag value carried through from the workspace''s outlets.',
    amenity = 'Element amenity tag value carried through from the workspace''s outlets.',
    food_class = 'healthy for a grocery outlet, unhealthy for a convenience store or fast-food outlet.',
    geometry = 'Outlet point re-tagged as SRID 4326 (degrees, EPSG:4326).'
  ),
  columns (
    osm_id BIGINT,
    name TEXT,
    shop TEXT,
    amenity TEXT,
    food_class TEXT,
    geometry GEOMETRY(Point, 4326)
  ),
  blueprints @workspace_blueprints()
);

-- Food outlets — PostGIS VIEW wrapping the DuckDB bridge table with a real SRID.
--
-- The bridge is the workspace's ``food_pois_input``: its Overpass fetch
-- (workspace_inputs/food_pois_fetch_raw.sql) or its package's outlets
-- (workspace_inputs/food_pois_package_raw.sql) — one VIEW over either, for the
-- reason workspace_inputs/constraint_layers.sql gives. Both bridges land through
-- DuckDB, and that transfer writes SRID-less WKB: every geometry
-- in the bridge lands as SRID 0 however the SELECT tagged it (see the bridge's
-- header). The tile server cannot repair that — Martin publishes a source from
-- the column's CRS and transforms it per tile, so a 0-SRID column answers every
-- tile request with ``ST_Transform: Input geometry has unknown (0) SRID`` — and
-- a registered Layer over the bridge therefore drew nothing on the map while its
-- rows still showed in the attribute table.
--
-- This VIEW restores the SRID with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes for its bridge, so both the tile server and
-- every PostGIS consumer read a geometry column that carries its CRS instead of
-- re-tagging it by hand.

SELECT
    osm_id,
    name,
    shop,
    amenity,
    food_class,
    ST_SetSRID(geometry, 4326) AS geometry
FROM brewgis.@{workspace_schema}.@{food_pois_input};
