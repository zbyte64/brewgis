MODEL (
  name brewgis.@{region}.poi,
  kind VIEW,
  description 'PostGIS VIEW over the region''s Overpass POI bridge that restores SRID metadata with ST_SetSRID: OpenStreetMap points of interest for the region, one point per OSM node or way.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    osm_type = 'OpenStreetMap element type, node or way.',
    name = 'Element name tag, empty string when the element is unnamed.',
    category = 'POI category owning the element''s first matching tag (macros/overpass_fetch.py taxonomy).',
    subcategory = 'The matched tag as key=value.',
    amenity = 'Element amenity tag value, empty string when absent.',
    shop = 'Element shop tag value, empty string when absent.',
    leisure = 'Element leisure tag value, empty string when absent.',
    tourism = 'Element tourism tag value, empty string when absent.',
    geometry = 'POI point re-tagged as SRID 4326 (degrees, EPSG:4326).'
  ),
  columns (
    osm_id BIGINT,
    osm_type TEXT,
    name TEXT,
    category TEXT,
    subcategory TEXT,
    amenity TEXT,
    shop TEXT,
    leisure TEXT,
    tourism TEXT,
    geometry GEOMETRY(Point, 4326)
  ),
  blueprints @region_blueprints()
);

-- OpenStreetMap points of interest for the region — PostGIS VIEW wrapping the
-- Overpass bridge with a real SRID, the repair ``osm/poi.sql`` makes for the
-- project-wide fetch and ``osm/food_pois.sql`` for the region food fetch.
--
-- The bridge (``brewgis.<region>.poi_raw``) materializes the fetch through
-- DuckDB, and that transfer writes SRID-less WKB: every geometry lands in the
-- bridge as SRID 0 however the SELECT tagged it (see the bridge's header).
-- Anything that reads the CRS — a tile server transforming a source per tile,
-- ``ST_Transform``, ``ST_Intersects`` against a projected column — then fails on
-- the bridge's own column.
--
-- This VIEW restores the SRID with ``ST_SetSRID``; it is the model the POI
-- built-form override joins.

SELECT
    osm_id,
    osm_type,
    name,
    category,
    subcategory,
    amenity,
    shop,
    leisure,
    tourism,
    ST_SetSRID(geometry, 4326) AS geometry
FROM brewgis.@{region}.poi_raw;
