MODEL (
  name duckdb.@{region}.food_pois,
  kind VIEW,
  description 'OpenStreetMap food outlets for the region, fetched from the Overpass API by DuckDB, one row per node or way, classified healthy or unhealthy for the food-access mRFEI.',
  column_descriptions (
    osm_id = 'OpenStreetMap element id within its element type.',
    name = 'Element name tag, empty string when the element is unnamed.',
    shop = 'Element shop tag value, empty string when absent.',
    amenity = 'Element amenity tag value, empty string when absent.',
    food_class = 'healthy for a grocery outlet, unhealthy for a convenience store or fast-food outlet (macros/overpass_fetch.py FOOD_ACCESS_CLASSES).',
    geometry = 'Outlet point in EPSG:4326: node lon/lat, or the way''s center.'
  ),
  gateway duckdb,
  dialect duckdb,
  -- Declared, as in osm/poi.sql, to pin the view's column order and types for
  -- the bridge reading through it. It does not spare the fetch: binding the
  -- SELECT against read_json_auto needs the response's schema, so creating this
  -- view issues the Overpass request (measured 2026-09-27: ~140 s cold), and
  -- DuckDB's httpfs cache is what makes a repeat read cheap — see the pre hook.
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

-- Overpass food outlets for the region — the fetch the food-access analysis
-- counts from, separate from the POI import's taxonomy-driven
-- ``duckdb.osm.poi``: this asks for exactly the tags the mRFEI splits on.
--
-- The bounding box is the region's Overture window expanded by
-- ``FOOD_ACCESS_BBOX_MARGIN`` degrees, because the metric counts outlets within
-- 1 km of a parcel and the demo regions' parcels run past that window (Fresno's
-- ~1.8 km south of its Overture bbox) — outlets there are only found if the
-- query reaches past it.
--
-- Overpass is queried over HTTP GET (DuckDB's httpfs cannot POST), with the
-- Overpass QL percent-encoded into the ``data`` parameter by
-- ``@food_access_url``. DuckDB's httpfs block cache holds the response, so a
-- repeated plan re-reads it instead of re-requesting it. ``out center;`` gives
-- ways a center coordinate, so node and way results both carry a point.

-- pre hooks
-- Creating this VIEW is what executes the Overpass request (DuckDB resolves its
-- schema even with the columns declared above), and httpfs gives a read 30 s per
-- attempt by default — shorter than this fetch's response time (~2 minutes; see
-- macros/overpass_fetch.py OVERPASS_URL). Raised for the session doing the read;
-- cache_httpfs serves the response from disk afterwards.
  SET http_timeout = 900;

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
