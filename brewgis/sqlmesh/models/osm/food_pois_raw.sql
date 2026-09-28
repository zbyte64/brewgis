MODEL (
  name brewgis.@{region}.food_pois_raw,
  kind FULL,
  description 'PostGIS bridge table materializing the DuckDB Overpass food-outlet fetch for the region, one point per OSM node or way.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag carried through from the DuckDB fetch.',
    shop = 'Element shop tag value carried through from the DuckDB fetch.',
    amenity = 'Element amenity tag value carried through from the DuckDB fetch.',
    food_class = 'healthy or unhealthy, carried through from the DuckDB fetch.',
    geometry = 'Outlet point in EPSG:4326 as the fetch produced it, stored with SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB, so this table carries no CRS. Read the food_pois model (the PostGIS VIEW that re-tags it) for a usable geometry column.'
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
-- PostGIS-accessible table.
--
-- Every geometry here lands as SRID 0: DuckDB's postgres extension writes
-- SRID-less WKB, so the ``ST_SetCRS`` this selects is not carried over (measured
-- 2026-09-27 against this DuckDB: a fresh ``CREATE TABLE … AS SELECT
-- ST_SetCRS(point, 'EPSG:4326')`` through the attach reads back as ``ST_SRID =
-- 0``), and the same SRID-less transfer in both directions is documented in
-- ``workspace/services/fetch_clone.py``. The SRID is therefore restored on the
-- PostGIS side: ``osm/food_pois.sql`` (the PostGIS VIEW over this table) re-tags
-- it with ``ST_SetSRID``, and that is the model consumers read.

SELECT
    osm_id,
    name,
    shop,
    amenity,
    food_class,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM duckdb.@{region}.food_pois;
