MODEL (
  name brewgis.assessor.overture_path_intersection_density,
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

-- Overture Path Intersection Density — per-parcel pedestrian path density.
--
-- Measures walkability by counting pedestrian path intersection points
-- (footways, pedestrian paths, cycleways, etc.) within 1/4-mile (402m)
-- of each parcel's centroid. Uses the same methodology as
-- overture_intersection_density but restricted to pedestrian-class paths.

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS path_intersection_density
    FROM brewgis.assessor.sacog_assessor_parcels sap
    LEFT JOIN brewgis.assessor.overture_path_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.path_intersection_density, 0.0) AS path_intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.assessor.sacog_assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_path_intersection_density_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_overture_path_intersection_density_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
