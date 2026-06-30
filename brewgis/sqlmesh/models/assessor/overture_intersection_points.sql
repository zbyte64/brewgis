MODEL (
  name brewgis.assessor.overture_intersection_points,
  kind FULL,
  column_descriptions (
    geometry = "Intersection point (snapped to 10m grid) in local_srid (3310)",
    street_count = "Number of road segments meeting at this intersection"
  )
);

-- Overture Intersection Points — pre-computed road intersection point features
-- with GiST index for performant ST_DWithin joins in intersection density.
--
-- Extracts endpoints from driveable Overture road segments, snaps to a 10m
-- grid to deduplicate, and keeps only points with ≥3 incident segments
-- (true intersections).

WITH driveable_segments AS (
    SELECT
        ST_Transform(
            ST_SetSRID(geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid', 3310)
        ) AS local_geometry
    FROM brewgis.staging.overture_transport
    WHERE class IN ('motorway', 'primary', 'secondary', 'tertiary', 'residential', 'service')
      AND geometry IS NOT NULL
),

endpoints AS (
    SELECT ST_StartPoint(local_geometry) AS pt FROM driveable_segments
    UNION ALL
    SELECT ST_EndPoint(local_geometry) AS pt FROM driveable_segments
),

snapped_endpoints AS (
    SELECT ST_SnapToGrid(pt, 10) AS snapped_location
    FROM endpoints
),

street_nodes AS (
    SELECT snapped_location AS geometry, COUNT(*) AS street_count
    FROM snapped_endpoints
    GROUP BY snapped_location
)

SELECT geometry, street_count
FROM street_nodes
WHERE street_count >= 3;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_points_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
