MODEL (
  name brewgis.@{region}.food_pois,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overpass food-outlet fetch for the region, one point per OSM node or way.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag carried through from the DuckDB fetch.',
    shop = 'Element shop tag value carried through from the DuckDB fetch.',
    amenity = 'Element amenity tag value carried through from the DuckDB fetch.',
    food_class = 'healthy or unhealthy, carried through from the DuckDB fetch.',
    geometry = 'Outlet point in EPSG:4326 as the fetch produced it; the SRID does not survive the DuckDB-to-PostGIS transfer, so consumers re-tag it (see food_pois_local.sql).'
  ),
  gateway duckdb,
  blueprints @region_blueprints()
);

-- NOTE: Audits intentionally omitted (gateway duckdb); the region's
-- food_pois_local audits the row count that reaches the analysis.

-- pre hooks
-- Reading the DuckDB VIEW executes the Overpass request, and httpfs gives it
-- 30 s per attempt by default — shorter than this fetch's response time (~2
-- minutes; see macros/overpass_fetch.py OVERPASS_URL). Raised for the session
-- doing the read; cache_httpfs serves the response from disk afterwards.
  SET http_timeout = 900;

-- Food outlets — bridge model that materializes the DuckDB Overpass VIEW into a
-- PostGIS-accessible table. ST_SetCRS records the SRID explicitly because the
-- DuckDB-to-PostGIS transfer drops SRID metadata (all geometries arrive as
-- SRID 0), mirroring osm/poi_bridge.sql.

SELECT
    osm_id,
    name,
    shop,
    amenity,
    food_class,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.@{region}.food_pois;
