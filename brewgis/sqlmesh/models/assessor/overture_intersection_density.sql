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

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS intersection_density
    FROM brewgis.assessor.sacog_assessor_parcels sap
    LEFT JOIN brewgis.assessor.overture_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.intersection_density, 0.0) AS intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.assessor.sacog_assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_apn
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_overture_intersection_density_geometry
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
