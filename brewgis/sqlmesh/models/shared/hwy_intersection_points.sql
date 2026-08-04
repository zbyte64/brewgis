MODEL (
  name brewgis.@{region}.hwy_intersection_points,
  kind FULL,
  column_descriptions (
    geometry = "Intersection point (snapped to 10m grid) in local_srid (3310)",
    street_count = "Number of highway segments meeting at this intersection"
  ),
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- pre hooks
-- (overture_transport is DuckDB gateway, so indexes must live here)
  CREATE INDEX IF NOT EXISTS idx_overture_transport_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (wgs84_geometry);
  CREATE INDEX IF NOT EXISTS idx_overture_transport_local_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (local_geometry);

-- Region Overture Highway Intersection Points — pre-computed highway
-- interchange points with GiST index for performant ST_DWithin joins.
--
-- Identical method to overture_intersection_points but filtered to
-- highway-class roads (motorway, motorway_link, trunk, trunk_link) instead of
-- all driveable roads. Overture transport data is global — the region is
-- determined by the staging VIEW's bbox variables — so the same SQL serves
-- every region.

WITH highway_segments AS (
    SELECT
        ST_Transform(
            ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid', 3310)
        ) AS local_geometry
    FROM brewgis.staging.overture_transport
    WHERE class IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')
      AND wgs84_geometry IS NOT NULL
),

endpoints AS (
    SELECT ST_StartPoint(local_geometry) AS pt FROM highway_segments
    UNION ALL
    SELECT ST_EndPoint(local_geometry) AS pt FROM highway_segments
),

snapped_endpoints AS (
    SELECT ST_SnapToGrid(pt, 10) AS snapped_location
    FROM endpoints
),

highway_nodes AS (
    SELECT snapped_location AS geometry, COUNT(*) AS street_count
    FROM snapped_endpoints
    GROUP BY snapped_location
)

SELECT geometry, street_count
FROM highway_nodes
WHERE street_count >= 3;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_hwy_intersection_points_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  ANALYZE @this_model;
