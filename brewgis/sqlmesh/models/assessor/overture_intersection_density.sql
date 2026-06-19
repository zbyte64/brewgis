MODEL (
  name brewgis.assessor.overture_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres
);

-- Overture Intersection Density — per-parcel intersection density using
-- ST_DWithin against pre-computed intersection points.
--
-- Replaces the earlier grid-based approach. Uses GiST-indexed ST_DWithin
-- to count intersection points within a 1/4-mile (402m) radius of each
-- parcel's centroid, leveraging the pre-computed overture_intersection_points
-- table which has a GiST index on geometry.
--
-- Density = intersection_count / (π * 402² / 2589988.11) intersections/sq mi.

WITH parcel_centroids AS (
    SELECT
        apn,
        ST_Centroid(
            ST_Transform(geometry, @VAR('local_srid', 3310))
        ) AS centroid,
        geometry
    FROM brewgis.assessor.sacog_assessor_parcels
    WHERE geometry IS NOT NULL
)

SELECT
    pc.apn,
    COALESCE(
        COUNT(i.geometry)::double precision
        / (PI() * 402.0 * 402.0 / 2589988.11),
        0.0
    ) AS intersection_density,
    pc.geometry
FROM parcel_centroids pc
LEFT JOIN brewgis.assessor.overture_intersection_points i
    ON ST_DWithin(pc.centroid, i.geometry, 402.0)
GROUP BY pc.apn, pc.geometry;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_apn
  ON brewgis.assessor.overture_intersection_density (apn);
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_geometry
  ON brewgis.assessor.overture_intersection_density USING GIST (geometry);
ANALYZE brewgis.assessor.overture_intersection_density;
