MODEL (
  name duckdb.@{region}.poi,
  kind VIEW,
  description 'DuckDB staging VIEW fetching OpenStreetMap points of interest for the region''s Overture bounding box from the Overpass API, one row per node or way.',
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
    geometry = 'POI point in EPSG:4326: node lon/lat, or the way''s center.'
  ),
  gateway duckdb,
  dialect duckdb,
  -- Declared, as in osm/poi_duckdb.sql, to pin the view's column order and types
  -- for the bridge reading through it.
  columns (
    osm_id BIGINT,
    osm_type VARCHAR,
    name VARCHAR,
    category VARCHAR,
    subcategory VARCHAR,
    amenity VARCHAR,
    shop VARCHAR,
    leisure VARCHAR,
    tourism VARCHAR,
    geometry GEOMETRY
  ),
  blueprints @region_blueprints()
);

-- OpenStreetMap points of interest for the region — the same taxonomy-driven
-- fetch as ``duckdb.osm.poi``, cut to the region's Overture bounding box so the
-- POI built-form override reads the region's own points rather than a
-- project-wide one.
--
-- Overpass is queried over HTTP GET (DuckDB's httpfs cannot POST), with the
-- Overpass QL query percent-encoded into the `data` parameter by
-- @overpass_url. `out center;` gives ways a center coordinate, so both node and
-- way results carry a point. The tag taxonomy (which tags are POIs, and which
-- category owns each) lives in macros/overpass_fetch.py — the same module
-- Django's POI import form reads its category list from, so the fetch and the
-- form cannot drift apart. Category and subcategory come from CASE expressions
-- generated there, evaluated in taxonomy order so an element carrying several
-- POI tags lands in the first category that claims one of them.
--
-- Creating this VIEW is what executes the Overpass request (DuckDB resolves its
-- schema even with the columns declared above), so the read has to outlast the
-- fetch's cold answer: that timeout and the retries around it come from the
-- gateway's connector_config (config.py). DuckDB's httpfs cache is what makes a
-- repeat read cheap.

WITH elements AS (
    SELECT unnest(elements) AS e
    FROM read_json_auto(
        @overpass_url(
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
),

classified AS (
    SELECT
        *,
        @poi_subcategory_case(tags_json) AS subcategory
    FROM raw
)

SELECT
    osm_id,
    osm_type,
    COALESCE(json_extract_string(tags_json, '$.name'), '')::VARCHAR AS name,
    @poi_category_case(subcategory) AS category,
    subcategory::VARCHAR AS subcategory,
    COALESCE(json_extract_string(tags_json, '$.amenity'), '')::VARCHAR AS amenity,
    COALESCE(json_extract_string(tags_json, '$.shop'), '')::VARCHAR AS shop,
    COALESCE(json_extract_string(tags_json, '$.leisure'), '')::VARCHAR AS leisure,
    COALESCE(json_extract_string(tags_json, '$.tourism'), '')::VARCHAR AS tourism,
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
FROM classified;
