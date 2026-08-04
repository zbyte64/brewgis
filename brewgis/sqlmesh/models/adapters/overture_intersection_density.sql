MODEL (
  name brewgis.@{region}.overture_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints (
    (region := sacog),
    (region := fresno)
  )
);

-- Overture Intersection Density — per-parcel intersection density using
-- ST_DWithin against pre-computed intersection points.
--
-- Identical logic for every region: counts intersection points within a
-- 1/4-mile (402m) radius of each assessor parcel's local centroid, using
-- the region's own ``@{region}.overture_intersection_points`` table.
--
-- Density = intersection_count / (π * 402² / 2589988.11) intersections/sq mi.

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS intersection_density
    FROM brewgis.@{region}.assessor_parcels sap
    LEFT JOIN brewgis.@{region}.overture_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.intersection_density, 0.0) AS intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.@{region}.assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_@{region}_intersection_density_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_@{region}_intersection_density_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
