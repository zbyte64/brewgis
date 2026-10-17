MODEL (
  name brewgis.@{region}.food_pois_raw,
  kind FULL,
  description 'OpenStreetMap food outlets for the region fetched from the Overpass API by DuckDB and materialized in PostGIS, one point per OSM node or way, classified healthy or unhealthy for the food-access mRFEI.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag, empty string when the element is unnamed.',
    shop = 'Element shop tag value, empty string when absent.',
    amenity = 'Element amenity tag value, empty string when absent.',
    food_class = 'healthy for a grocery outlet, unhealthy for a convenience store or fast-food outlet (macros/overpass_fetch.py FOOD_ACCESS_CLASSES).',
    geometry = 'Outlet point in EPSG:4326 (node lon/lat, or the way''s center), stored with SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB, so this table carries no CRS. Read the food_pois model (the PostGIS VIEW that re-tags it) for a usable geometry column.'
  ),
  gateway duckdb,
  dialect duckdb,
  -- Declared so SQLMesh creates the table from this schema instead of binding
  -- the SELECT to learn it: every bind of read_json_auto re-sends the Overpass
  -- request (see the header).
  columns (
    osm_id BIGINT,
    name VARCHAR,
    shop VARCHAR,
    amenity VARCHAR,
    food_class VARCHAR,
    geometry GEOMETRY
  ),
  blueprints @region_blueprints()
);

-- NOTE: Audits intentionally omitted (gateway duckdb); the region's
-- food_pois_local audits the row count that reaches the analysis.

-- Overpass food outlets for the region — the fetch the food-access analysis
-- counts from, separate from the POI import's taxonomy-driven
-- ``brewgis.osm.poi_raw``: this asks for exactly the tags the mRFEI splits on.
--
-- The bounding box is the region's Overture window expanded by
-- ``FOOD_ACCESS_BBOX_MARGIN`` degrees, because the metric counts outlets within
-- 1 km of a parcel and the demo regions' parcels run past that window (Fresno's
-- ~1.8 km south of its Overture bbox) — outlets there are only found if the
-- query reaches past it.
--
-- Overpass is queried over HTTP GET (DuckDB's httpfs cannot POST), with the
-- Overpass QL percent-encoded into the ``data`` parameter by
-- ``@food_access_url``. ``out center;`` gives ways a center coordinate, so node
-- and way results both carry a point.
--
-- The fetch lives in this FULL model, not in a DuckDB staging VIEW in front of
-- it: DuckDB re-binds a view's read_json_auto — re-sending the request — every
-- time anything is built or selected on top of it (SQLMesh's promotion view
-- included), and cache_httpfs cannot serve an Overpass reply (no Content-Length,
-- Range ignored, so httpfs takes its full-download path, which bypasses the
-- block cache). Measured 2026-10-17 against a local server answering the way
-- Overpass does: every bind of such a view sent HEAD + GET; a view over this
-- table sends nothing. So Overpass is queried once per build of this model, and
-- the request's timeout and retries come from the gateway's connector_config
-- (config.py).
--
-- Every geometry here lands as SRID 0: DuckDB's postgres extension writes
-- SRID-less WKB, so the ``ST_SetCRS`` this selects is not carried over (measured
-- 2026-09-27 against this DuckDB: a fresh ``CREATE TABLE … AS SELECT
-- ST_SetCRS(point, 'EPSG:4326')`` through the attach reads back as ``ST_SRID =
-- 0``), and the same SRID-less transfer in both directions is documented in
-- ``workspace/services/fetch_clone.py``. The SRID is therefore restored on the
-- PostGIS side: ``osm/food_pois.sql`` (the PostGIS VIEW over this table) re-tags
-- it with ``ST_SetSRID``, and that is the model consumers read.

WITH elements AS (
    SELECT unnest(elements) AS e
    FROM read_json_auto(
        @food_access_url(
            @overture_bbox_min_x,
            @overture_bbox_min_y,
            @overture_bbox_max_x,
            @overture_bbox_max_y
        ),
        format = 'auto'
    )
),

raw AS (
    SELECT
        e.id::BIGINT AS osm_id,
        e.type::VARCHAR AS osm_type,
        to_json(e) AS element_json,
        to_json(e.tags) AS tags_json
    FROM elements
    WHERE e.type IN ('node', 'way')
)

SELECT
    osm_id,
    COALESCE(json_extract_string(tags_json, '$.name'), '')::VARCHAR AS name,
    COALESCE(json_extract_string(tags_json, '$.shop'), '')::VARCHAR AS shop,
    COALESCE(json_extract_string(tags_json, '$.amenity'), '')::VARCHAR AS amenity,
    @food_access_class_case(tags_json) AS food_class,
    ST_SetCRS(
        ST_Point(
            COALESCE(
                json_extract_string(element_json, '$.lon'),
                json_extract_string(element_json, '$.center.lon'),
                '0'
            )::DOUBLE,
            COALESCE(
                json_extract_string(element_json, '$.lat'),
                json_extract_string(element_json, '$.center.lat'),
                '0'
            )::DOUBLE
        ),
        'EPSG:4326'
    ) AS geometry
FROM raw;
