AUDIT (
  name assert_bft_tier3b_footprint_filter,
  dialect postgres
);
-- lot>3ac + footprint_ratio<0.02 → agricultural (Tier 3b)
-- Excludes A2% parcels (multi-family) which correctly fall through to tier4.
-- Reads from tier3b model (apn, 'agricultural') and JOINs source tables.
SELECT
  t3b.apn,
  ap.lot_size_acres,
  COALESCE(bs.footprint_ratio, 0) AS footprint_ratio,
  t3b.built_form_key
FROM @this_model t3b
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t3b.apn = ap.apn
LEFT JOIN brewgis.assessor.parcel_building_sqft_by_type bs ON t3b.apn = bs.apn
WHERE ap.lot_size_acres > 3.0
  AND COALESCE(bs.footprint_ratio, 0) < 0.02
  AND COALESCE(t3b.built_form_key, '') != 'agricultural';
