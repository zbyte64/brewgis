MODEL (
  name brewgis.@{region}.overture_intersection_density,
  kind INCREMENTAL_BY_UNIQUE_KEY (
    unique_key (apn),
    batch_size 100000
  ),
  description 'Per-parcel Overture intersection density: intersection points counted within 402 m (a quarter mile) of the parcel local centroid, one row per assessor parcel APN.',
  column_descriptions (
    apn = 'Assessor parcel number (APN) of the parcel the density belongs to.',
    intersection_density = 'Overture intersection points within 402 m of the parcel local centroid, per square mile.',
    geometry = 'Parcel geometry taken from the region assessor parcels table, joined by APN.'
  ),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))
  ),
  dialect postgres,
  blueprints @region_blueprints()
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
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_intersection_density_apn_')
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS @snapshot_hash('idx_intersection_density_geometry_')
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
