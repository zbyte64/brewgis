MODEL (
  name brewgis.assessor.overture_path_intersection_points,
  kind FULL,
  column_descriptions (
    geometry = "Intersection point (snapped to 10m grid) in local_srid (3310)",
    street_count = "Number of path segments meeting at this intersection"
  )
);

-- pre hooks
-- (overture_transport is DuckDB gateway, so indexes must live here)
  CREATE INDEX IF NOT EXISTS idx_overture_transport_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (geometry);
  CREATE INDEX IF NOT EXISTS idx_overture_transport_local_geometry_@snapshot_hash
  ON brewgis.staging.overture_transport USING GIST (local_geometry);

-- Overture Path Intersection Points — pre-computed pedestrian path
-- intersection points with GiST index.
--
-- Identical method to overture_intersection_points but filtered to
-- pedestrian-class paths (footway, pedestrian, steps, path, cycleway)
-- instead of driveable roads. Captures fine-grained walkability
-- independently of the driveable road grid.

WITH path_segments AS (
    SELECT
        ST_Transform(
            ST_SetSRID(geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid', 3310)
        ) AS local_geometry
    FROM brewgis.staging.overture_transport
    WHERE class IN ('footway', 'pedestrian', 'steps', 'path', 'cycleway')
      AND geometry IS NOT NULL
),

endpoints AS (
    SELECT ST_StartPoint(local_geometry) AS pt FROM path_segments
    UNION ALL
    SELECT ST_EndPoint(local_geometry) AS pt FROM path_segments
),

snapped_endpoints AS (
    SELECT ST_SnapToGrid(pt, 10) AS snapped_location
    FROM endpoints
),

path_nodes AS (
    SELECT snapped_location AS geometry, COUNT(*) AS street_count
    FROM snapped_endpoints
    GROUP BY snapped_location
)

SELECT geometry, street_count
FROM path_nodes
WHERE street_count >= 3;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_path_intersection_points_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
