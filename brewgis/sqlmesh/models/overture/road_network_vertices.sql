MODEL (
  name brewgis.@{region}.road_network_vertices,
  kind FULL,
  description 'Vertices of the region''s undirected drivable road graph: one node per Overture connector, deduplicated by connector id and positioned by interpolation along its segment.',
  column_descriptions (
    id = 'pgRouting vertex id (dense, ordered by connector id)',
    connector_id = 'Overture connector id shared by the segments meeting at this junction',
    geometry = 'Vertex point in local_srid'
  ),
  audits (
    not_null(columns := (id, connector_id)),
    unique_values(columns := (id, connector_id))
  ),
  blueprints @region_blueprints()
);

-- pre hooks
-- pgr_dijkstraCost (network_zone_distance) reads the graph these two models
-- build; the extension ships with the PostGIS image.
  CREATE EXTENSION IF NOT EXISTS pgrouting WITH SCHEMA public;

-- Region road network vertices — the node table of the drivable graph that
-- road_network_edges connects.
--
-- Topology comes from Overture's own connectors: one vertex per distinct
-- connector id, placed by interpolating the fraction (`at`) the connector sits
-- at along a segment it touches. Connector ids are shared by every segment
-- meeting at a junction, so this joins exactly where Overture says the roads
-- do — unlike snapping segment endpoints to a grid, which left 82% of zone
-- pairs with no path.
--
-- Simplifications (shared with road_network_edges): the graph is undirected —
-- one-way and access rules are ignored.
--
-- A connector's `at` fraction is identical on every segment that reports it,
-- but the interpolated point is taken from one segment only
-- (`DISTINCT ON (connector_id)`), so its coordinates are that segment's.

WITH occ AS (
    SELECT from_connector_id AS connector_id, from_at AS at,
           ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid')) AS g
    FROM brewgis.@{region}.overture_road_subsegments
    UNION ALL
    SELECT to_connector_id, to_at,
           ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid'))
    FROM brewgis.@{region}.overture_road_subsegments
),
pts AS (
    SELECT DISTINCT ON (connector_id)
           connector_id,
           ST_LineInterpolatePoint(g, at) AS p
    FROM occ
    ORDER BY connector_id, at
)
SELECT
    ROW_NUMBER() OVER (ORDER BY connector_id)::BIGINT AS id,
    connector_id,
    p AS geometry
FROM pts;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_vertices_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_vertices_connector_')
  ON @this_model USING btree (connector_id);
  ANALYZE @this_model;
