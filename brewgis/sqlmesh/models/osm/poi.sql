MODEL (
  name brewgis.osm.poi,
  kind VIEW,
  description 'PostGIS VIEW over the Overpass POI bridge that restores SRID metadata with ST_SetSRID: OpenStreetMap points of interest, one point per OSM node or way.',
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
  )
);

-- OpenStreetMap points of interest — PostGIS VIEW wrapping the Overpass bridge
-- with a real SRID.
--
-- The bridge (``brewgis.osm.poi_raw``) materializes the fetch through DuckDB,
-- and that transfer writes SRID-less WKB: every geometry lands in the bridge as
-- SRID 0 however the SELECT tagged it (see the bridge's header). Anything that
-- reads the CRS — a tile server transforming a source per tile, ``ST_Transform``,
-- a ``create_layer`` registration — then fails on the bridge's own column.
--
-- This VIEW restores the SRID with ``ST_SetSRID``, the same repair
-- ``census/tiger_blocks.sql`` makes for its bridge. The Import Center clones
-- *this* model (``services/poi_fetcher.py``), so an imported POI layer carries
-- its CRS from here instead of being repaired after the copy.

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
FROM brewgis.osm.poi_raw;
