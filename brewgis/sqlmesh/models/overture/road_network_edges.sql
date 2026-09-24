MODEL (
  name brewgis.@{region}.road_network_edges,
  kind FULL,
  description 'Edges of the region''s undirected drivable road graph: one row per Overture subsegment (consecutive connector pair), costed by its length in metres.',
  column_descriptions (
    id = 'pgRouting edge id (dense, ordered by source, target, cost_m)',
    source = 'Vertex id (road_network_vertices.id) at the subsegment start connector',
    target = 'Vertex id (road_network_vertices.id) at the subsegment end connector',
    cost_m = 'Subsegment length in metres, the edge traversal cost',
    geometry = 'Subsegment line in local_srid'
  ),
  audits (
    not_null(columns := (id, source, target)),
    assert_column_non_negative(column_name := cost_m),
    -- Same floor rationale as overture_intersection_points: SACOG and Fresno
    -- both carry far more drivable subsegments than this, so the floor catches
    -- an empty/broken subsegment bridge.
    assert_row_count_between(min_rows := 20000, max_rows := 100000000)
  ),
  blueprints @region_blueprints()
);

-- Region road network edges — the edge table pgr_dijkstraCost walks for
-- network_zone_distance.
--
-- One edge per consecutive connector pair of a drivable segment, with
-- source/target resolved through road_network_vertices.connector_id, the
-- junction topology Overture itself records.
--
-- Cost is the length of the substring between the pair's two `at` fractions,
-- measured in local_srid and converted to metres, so a segment's subsegment
-- costs still sum to its full length.
--
-- Simplifications (shared with road_network_vertices): undirected — one-way
-- and access rules are ignored. A segment's consecutive connectors are always
-- distinct, so the `source <> target` guard only drops degenerate rows.
--
-- Geometry is recomputed from the `at` fractions rather than carried per
-- subsegment: the bridge stores one geometry per segment.

WITH sub AS (
    SELECT
        from_connector_id,
        to_connector_id,
        @local_length_metres(ST_Length(ST_LineSubstring(g, from_at, to_at))) AS cost_m,
        ST_LineSubstring(g, from_at, to_at) AS geometry
    FROM (
        SELECT
            from_connector_id, from_at, to_connector_id, to_at,
            ST_Transform(ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)), @VAR('local_srid')) AS g
        FROM brewgis.@{region}.overture_road_subsegments
    ) d
)
SELECT
    ROW_NUMBER() OVER (ORDER BY s.id, t.id, sub.cost_m)::BIGINT AS id,
    s.id AS source,
    t.id AS target,
    sub.cost_m,
    sub.geometry
FROM sub
INNER JOIN brewgis.@{region}.road_network_vertices AS s
    ON s.connector_id = sub.from_connector_id
INNER JOIN brewgis.@{region}.road_network_vertices AS t
    ON t.connector_id = sub.to_connector_id
WHERE s.id <> t.id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_edges_source_')
  ON @this_model USING btree (source);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_edges_target_')
  ON @this_model USING btree (target);
  ANALYZE @this_model;
