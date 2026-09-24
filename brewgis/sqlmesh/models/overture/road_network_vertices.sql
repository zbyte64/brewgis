MODEL (
  name brewgis.@{region}.road_network_vertices,
  kind FULL,
  description 'Vertices of the region''s undirected drivable road graph: Overture transport segment endpoints snapped to a 10 m grid and deduplicated, one row per graph node.',
  column_descriptions (
    id = 'pgRouting vertex id (dense, ordered by x then y)',
    x = 'Snapped vertex x coordinate in local_srid units',
    y = 'Snapped vertex y coordinate in local_srid units',
    geometry = 'Snapped vertex point in local_srid'
  ),
  audits (
    not_null(columns := (id)),
    unique_values(columns := (id,))
  ),
  blueprints @region_blueprints()
);

-- pre hooks
-- pgr_dijkstraCost (network_zone_distance) reads the graph these two models
-- build; the extension ships with the PostGIS image.
  CREATE EXTENSION IF NOT EXISTS pgrouting WITH SCHEMA public;
-- (overture_transport is DuckDB gateway, so indexes must live here)
  DO $$ BEGIN PERFORM pg_advisory_xact_lock(hashtext('idx_overture_transport_geometry')::bigint); END $$;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_transport_geometry_')
  ON brewgis.@{region}.overture_transport USING GIST (wgs84_geometry);
  DO $$ BEGIN PERFORM pg_advisory_xact_lock(hashtext('idx_overture_transport_local_geometry')::bigint); END $$;
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_overture_transport_local_geometry_')
  ON brewgis.@{region}.overture_transport USING GIST (local_geometry);

-- Region road network vertices — the node table of the drivable graph that
-- road_network_edges connects.
--
-- Simplifications (shared with road_network_edges): the graph is undirected
-- (one-way and access rules are ignored), and topology comes from segment
-- endpoints snapped to a 10 m grid — the approximation
-- overture_intersection_points uses; Overture connectors are not read. The
-- snapping expression must stay identical to road_network_edges', which joins
-- back onto (x, y).

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

pts AS (
    SELECT ST_SnapToGrid(ST_StartPoint(g), @metres_in_local_units(10)) AS p FROM drive
    UNION
    SELECT ST_SnapToGrid(ST_EndPoint(g), @metres_in_local_units(10)) AS p FROM drive
)

SELECT
    ROW_NUMBER() OVER (ORDER BY ST_X(p), ST_Y(p))::BIGINT AS id,
    ST_X(p) AS x,
    ST_Y(p) AS y,
    p AS geometry
FROM pts;

-- post_statements
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_vertices_geometry_')
  ON @this_model USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_road_network_vertices_xy_')
  ON @this_model USING btree (x, y);
  ANALYZE @this_model;
