MODEL (
  name brewgis.osm.poi_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overpass POI fetch, one point per OSM node or way; the geometry column lands as SRID 0.',
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
    geometry = 'POI point in EPSG:4326 stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB (see the header). Read brewgis.osm.poi for the re-tagged column.'
  ),
  gateway duckdb
);

-- Overpass POI bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Point emits EPSG:4326 geometry, but the DuckDB-to-PostGIS transfer
-- writes SRID-less WKB: the ``ST_SetCRS`` this SELECT applies is not carried
-- over, and every geometry lands as SRID 0 (measured against this stack; the
-- probe is recorded in ``osm/food_pois_raw.sql``). PostGIS consumers therefore
-- read the published ``brewgis.osm.poi`` VIEW, which re-tags the column, rather
-- than this bridge.
--
-- Django's POI import drives this model through ``services/poi_fetcher.py`` and
-- clones the published VIEW into the workspace's own schema, so the copy carries
-- a recorded CRS.

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
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.osm.poi;
