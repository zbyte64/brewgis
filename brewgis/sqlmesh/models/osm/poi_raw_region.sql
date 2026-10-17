MODEL (
  name brewgis.@{region}.poi_raw,
  kind FULL,
  description 'OpenStreetMap points of interest for the region''s Overture bounding box fetched from the Overpass API by DuckDB and materialized in PostGIS, one point per OSM node or way; the geometry column lands as SRID 0.',
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
    geometry = 'POI point in EPSG:4326 (node lon/lat, or the way''s center) stored as SRID 0: the DuckDB-to-PostGIS transfer writes SRID-less WKB (see the header). Read brewgis.<region>.poi for the re-tagged column.'
  ),
  gateway duckdb,
  dialect duckdb,
  -- Declared so SQLMesh creates the table from this schema instead of binding
  -- the SELECT to learn it (see osm/food_pois_raw.sql).
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
-- fetch as ``brewgis.osm.poi_raw``, cut to the region's Overture bounding box so
-- the POI built-form override reads the region's own points rather than a
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
-- The fetch lives in this FULL model rather than a DuckDB staging VIEW so
-- Overpass is queried once per build, never on promotion or on a read: see
-- osm/food_pois_raw.sql for the measurement.
--
-- DuckDB ST_Point emits EPSG:4326 geometry, but the DuckDB-to-PostGIS transfer
-- writes SRID-less WKB: the ``ST_SetCRS`` this SELECT applies is not carried
-- over, and every geometry lands as SRID 0 (the probe is recorded in
-- ``osm/food_pois_raw.sql``). The region's PostGIS consumers therefore read the
-- published ``brewgis.<region>.poi`` VIEW, which re-tags the column, rather than
-- this table.

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
