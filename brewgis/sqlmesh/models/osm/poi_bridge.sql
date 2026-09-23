MODEL (
  name brewgis.osm.poi,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overpass POI fetch, one point per OSM node or way.',
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
    geometry = 'POI point in EPSG:4326, wrapped in ST_SetCRS so the SRID survives the DuckDB-to-PostGIS FDW.'
  ),
  gateway duckdb
);

-- Overpass POI bridge — materializes the DuckDB fetch VIEW into PostGIS.
--
-- DuckDB ST_Point emits EPSG:4326 geometry. ST_SetCRS records the SRID
-- explicitly because the DuckDB→PostGIS FDW drops SRID metadata (all
-- geometries arrive as SRID 0), mirroring fresno/farmland_raw.sql.
--
-- The bridge is what Django's POI import copies out: tasks.run_poi_fetch runs
-- the plan that materializes this model and then clones it into the
-- workspace's own schema.

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
