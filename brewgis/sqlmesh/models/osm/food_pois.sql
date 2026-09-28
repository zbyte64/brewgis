MODEL (
  name brewgis.@{region}.food_pois,
  kind VIEW,
  description 'PostGIS VIEW over the food-outlet bridge that restores SRID metadata with ST_SetSRID: the region''s Overpass food outlets, one point per OSM node or way.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag carried through from the region fetch.',
    shop = 'Element shop tag value carried through from the region fetch.',
    amenity = 'Element amenity tag value carried through from the region fetch.',
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
  blueprints @region_blueprints()
);

-- Food outlets — PostGIS VIEW wrapping the DuckDB bridge table with a real SRID.
--
-- The bridge (``brewgis.<region>.food_pois_raw``) materializes the Overpass
-- fetch through DuckDB, and that transfer writes SRID-less WKB: every geometry
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
FROM brewgis.@{region}.food_pois_raw;
