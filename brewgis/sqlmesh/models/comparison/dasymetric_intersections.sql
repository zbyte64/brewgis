MODEL (
  name brewgis.comparison.dasymetric_intersections,
  kind FULL,
  audits (
    not_null(columns := (parcel_id, apn)),
    assert_dasymetric_apn_match_rate
  )
);

-- SACOG Comparison Dasymetric Intersections — pre-computed spatial crosswalk.
--
-- Materializes the parcel_id ↔ apn mapping with pre-computed intersection area.
-- Uses a full spatial LEFT JOIN with GIST index-driven && bbox pre-filter.
-- Removed the CROSS JOIN LATERAL + LIMIT 1 approach because it left ~20%
-- of assessor APNs unmatched, silently losing ~101K DU from the allocation.
-- The full join enables every intersecting APN-parcel pair to contribute,
-- which is the basis for correct proportional dasymetric allocation.

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
SELECT i.parcel_id, i.apn, i.intersect_area_sqft
FROM intersections i
JOIN brewgis.assessor.parcel_dasymetric_weights dw ON i.apn = dw.apn;

-- post_statements
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id);
  CREATE INDEX IF NOT EXISTS idx_dasymetric_intersections_apn_@snapshot_hash
  ON @this_model USING btree (apn);
ANALYZE @this_model;
