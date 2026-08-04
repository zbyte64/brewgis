MODEL (
  name brewgis.@{region}.overture_intersection_points,
  kind FULL,
  column_descriptions (
    geometry = "Intersection point (snapped to 10m grid) in local_srid (3310)",
    street_count = "Number of road segments meeting at this intersection"
  ),
  audits (
    -- Also covers transport-data availability from overture_transport:
    -- if that bridge produces <50000 rows, the intersection count drops
    -- below threshold and this audit fails.
    assert_row_count_between (min_rows := 50000, max_rows := 100000000)
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

-- Region Overture Intersection Points — pre-computed road intersection points
-- with GiST index for performant ST_DWithin joins in intersection density.
--
-- Identical logic for every region: extracts endpoints from driveable Overture
-- road segments, snaps to a 10m grid to deduplicate, and keeps only points
-- with ≥3 incident segments (true intersections). Reads from the PostgreSQL
-- bridge table (already materialized from DuckDB).

WITH driveable_segments AS (
    SELECT
        ST_Transform(
            ST_SetSRID(wgs84_geometry, @VAR('default_srid', 4326)),
            @VAR('local_srid', 3310)
        ) AS local_geometry
    FROM brewgis.staging.overture_transport
    WHERE class IN ('motorway', 'primary', 'secondary', 'tertiary', 'residential', 'service')
      AND wgs84_geometry IS NOT NULL
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
  CREATE INDEX IF NOT EXISTS idx_@{region}_intersection_points_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
  ANALYZE @this_model;
