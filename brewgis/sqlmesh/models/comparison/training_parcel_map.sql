MODEL (
  name brewgis.comparison.training_parcel_map,
  kind FULL,
  audits (
    not_null(columns := (parcel_id, apn))
  )
);

-- Reference-Parcel-to-Assessor-APN crosswalk for regressor training data.
-- Same spatial join as dasymetric_intersections but deliberately excludes
-- the parcel_dasymetric_weights filter to avoid a DAG cycle:
--   dasymetric_intersections → parcel_dasymetric_weights → regressor → dasymetric_intersections
--
-- The regressor applies its own feature-table LEFT JOINs + COALESCE(…, 0)
-- to handle unmatched APNs — no dasymetric filter is needed here.

WITH intersections AS (
    SELECT
        sp.parcel_id,
        ap.apn,
        ST_Area(ST_Intersection(ST_Envelope(sp.geometry), ST_Envelope(ap.geometry))) AS intersect_area_sqft
    FROM brewgis.comparison.sacog_parcel_shim sp
    JOIN brewgis.assessor.sacog_assessor_parcels ap
        ON ap.geometry && sp.geometry
        AND ST_Intersects(sp.geometry, ap.geometry)
)
SELECT DISTINCT ON (parcel_id, apn)
    parcel_id,
    apn,
    intersect_area_sqft
FROM intersections
ORDER BY parcel_id, apn, intersect_area_sqft DESC;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_training_parcel_map_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_training_parcel_map_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
