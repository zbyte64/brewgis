MODEL (
  name brewgis.fresno.dasymetric_intersections,
  kind FULL,
  audits (
    not_null(columns := (parcel_id, apn))
  )
);

-- Fresno Dasymetric Intersections — 1:1 crosswalk.
--
-- Fresno parcels lack assessor APNs, so each parcel_id maps to itself as apn
-- with a full (1.0) intersection area. This satisfies the same column contract
-- as brewgis.comparison.dasymetric_intersections for use in comparison_dasymetric.

SELECT
    parcel_id,
    parcel_id AS apn,
    1.0::double precision AS intersect_area_sqft
FROM brewgis.fresno.parcel_shim;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_fresno_dasymetric_intersections_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_fresno_dasymetric_intersections_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
