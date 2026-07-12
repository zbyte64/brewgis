MODEL (
  name brewgis.assessor.overture_highway_intersection_density,
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

-- Overture Highway Intersection Density — per-parcel highway interchange density.
--
-- Measures accessibility to highway infrastructure (motorways, trunk roads)
-- by counting highway intersection points within 1/4-mile (402m) of each
-- parcel's centroid. Uses the same methodology as overture_intersection_density
-- but restricted to highway-class roads.

WITH density AS (
    SELECT
        sap.apn,
        COUNT(i.geometry)::double precision
            / (PI() * 402.0 * 402.0 / 2589988.11) AS highway_intersection_density
    FROM brewgis.assessor.sacog_assessor_parcels sap
    LEFT JOIN brewgis.assessor.overture_highway_intersection_points i
        ON ST_DWithin(sap.centroid_local, i.geometry, 402.0)
    GROUP BY sap.apn
)
SELECT
    d.apn,
    COALESCE(d.highway_intersection_density, 0.0) AS highway_intersection_density,
    sap.geometry
FROM density d
JOIN brewgis.assessor.sacog_assessor_parcels sap ON d.apn = sap.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_overture_hwy_intersection_density_apn_@snapshot_hash
  ON @this_model USING btree (apn);
  CREATE INDEX IF NOT EXISTS idx_overture_hwy_intersection_density_geometry_@snapshot_hash
  ON @this_model USING GIST (geometry);
ANALYZE @this_model;
