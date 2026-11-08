MODEL (
  name brewgis.@{workspace_schema}.food_pois_package_raw,
  kind FULL,
  description 'Food outlets shipped in the workspace package (the exporting workspace''s OpenStreetMap fetch), materialized in PostGIS by DuckDB, one point per OSM node or way, classified healthy or unhealthy for the food-access mRFEI.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag, empty string when the element is unnamed.',
    shop = 'Element shop tag value, empty string when absent.',
    amenity = 'Element amenity tag value, empty string when absent.',
    food_class = 'healthy for a grocery outlet, unhealthy for a convenience store or fast-food outlet (macros/overpass_fetch.py FOOD_ACCESS_CLASSES).',
    geometry = 'Outlet point in EPSG:4326 stored with SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB. Read the food_pois model (the PostGIS VIEW that re-tags it) for a usable geometry column.'
  ),
  gateway duckdb,
  dialect duckdb,
  columns (
    osm_id BIGINT,
    name VARCHAR,
    shop VARCHAR,
    amenity VARCHAR,
    food_class VARCHAR,
    geometry GEOMETRY
  ),
  blueprints @workspace_blueprints('package_public_data')
);

-- Packaged food outlets — the same contract as the Overpass fetch
-- (workspace_inputs/food_pois_fetch_raw.sql), read from the ``food_pois`` part
-- of the package a workspace was imported from when its package shipped its
-- public data (``Workspace.public_data_source = package``), so the importing
-- server never queries Overpass. ``food_pois`` and ``food_pois_local`` read
-- this bridge whatever its source.
--
-- The part is a local GeoParquet file, read in the bridge itself: there is no
-- remote fetch for a staging VIEW to cache. Its geometry is EPSG:4326 (the
-- package format's one CRS), re-tagged on the PostGIS side like every bridge.

SELECT
    osm_id::BIGINT AS osm_id,
    name::VARCHAR AS name,
    shop::VARCHAR AS shop,
    amenity::VARCHAR AS amenity,
    food_class::VARCHAR AS food_class,
    ST_SetCRS(geometry, 'EPSG:4326') AS geometry
FROM read_parquet(@food_pois_parquet);
