MODEL (
  name brewgis.@{region}.road_network_edges,
  kind FULL,
  description 'Edges of the region''s undirected drivable road graph: one row per drivable Overture transport segment, connecting the road_network_vertices its snapped endpoints fall on, costed by length in metres.',
  column_descriptions (
    id = 'pgRouting edge id (dense, ordered by source, target, cost_m)',
    source = 'Vertex id (road_network_vertices.id) at the segment start point',
    target = 'Vertex id (road_network_vertices.id) at the segment end point',
    cost_m = 'Segment length in metres, the edge traversal cost',
    geometry = 'Segment line in local_srid'
  ),
  audits (
    not_null(columns := (id, source, target)),
    assert_column_non_negative(column_name := cost_m),
    -- Same floor rationale as overture_intersection_points: SACOG and Fresno
    -- both carry far more drivable segments than this, so the floor catches an
    -- empty/broken transport bridge.
    assert_row_count_between(min_rows := 20000, max_rows := 100000000)
  ),
  blueprints @region_blueprints()
);

-- pre hooks
-- (overture_transport is DuckDB gateway, so indexes must live here)
  DO $$ BEGIN PERFORM pg_advisory_xact_lock(hashtext('idx_overture_transport_geometry')::bigint); END $$;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_transport_geometry_')
  ON brewgis.@{region}.overture_transport USING GIST (wgs84_geometry);
  DO $$ BEGIN PERFORM pg_advisory_xact_lock(hashtext('idx_overture_transport_local_geometry')::bigint); END $$;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_transport_local_geometry_')
  ON brewgis.@{region}.overture_transport USING GIST (local_geometry);

-- Region road network edges — the edge table pgr_dijkstraCost walks for
-- network_zone_distance.
--
-- Simplifications (shared with road_network_vertices): undirected (one-way and
-- access rules ignored); a segment connects only at its endpoints, snapped to a
-- 10 m grid with the exact expression road_network_vertices uses, so the
-- (x, y) join below lands on the vertex rows. Segments whose two endpoints
-- snap to the same vertex are loops that never shorten a path and are dropped.

WITH drive AS (
    SELECT
        ST_Transform(
            ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid')
        ) AS g
    FROM brewgis.@{region}.overture_transport
    WHERE class IN (
        'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
        'residential', 'living_street', 'unclassified', 'service'
    )
      AND wgs84_geometry IS NOT NULL
      AND ST_GeometryType(wgs84_geometry) = 'ST_LineString'
),

snapped AS (
    SELECT
        g,
        ST_SnapToGrid(ST_StartPoint(g), @metres_in_local_units(10)) AS sp,
        ST_SnapToGrid(ST_EndPoint(g), @metres_in_local_units(10)) AS ep,
        @local_length_metres(ST_Length(g)) AS cost_m
    FROM drive
)

SELECT
    ROW_NUMBER() OVER (ORDER BY s.id, t.id, snapped.cost_m)::BIGINT AS id,
    s.id AS source,
    t.id AS target,
    snapped.cost_m,
    snapped.g AS geometry
FROM snapped
INNER JOIN brewgis.@{region}.road_network_vertices AS s
    ON s.x = ST_X(snapped.sp) AND s.y = ST_Y(snapped.sp)
INNER JOIN brewgis.@{region}.road_network_vertices AS t
    ON t.x = ST_X(snapped.ep) AND t.y = ST_Y(snapped.ep)
WHERE s.id <> t.id;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_edges_source_')
  ON @this_model USING btree (source);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_edges_target_')
  ON @this_model USING btree (target);
  ANALYZE @this_model;
