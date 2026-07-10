AUDIT (
  name assert_bft_tier4_area_heuristic,
  dialect postgres
);
-- lot>10ac → bt__agriculture; 3-10ac+zone%A% → bt__agriculture
-- Excludes A2% parcels (multi-family) which correctly get bt__medium_density_attached_residential from tier4.
-- Reads from tier4 model (apn, built_form_key) and JOINs assessor for landuse.
SELECT
  t4.apn,
  ap.lot_size_acres,
  ap.zone,
  t4.built_form_key,
  CASE
    WHEN ap.lot_size_acres > 10.0 THEN 'bt__agriculture'
    WHEN ap.lot_size_acres > 3.0 AND ap.zone LIKE '%A%' THEN 'bt__agriculture'
    WHEN ap.lot_size_acres > 3.0 AND ap.zone NOT LIKE '%A%' THEN 'bt__low_density_detached_residential'
    WHEN ap.lot_size_acres > 0.15 THEN 'bt__low_density_detached_residential'
    WHEN ap.lot_size_acres > 0.01 THEN 'bt__medium_density_detached_residential'
  END AS expected_bft
FROM @this_model t4
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t4.apn = ap.apn
WHERE ap.lot_size_acres IS NOT NULL
  AND t4.built_form_key IS NOT NULL
  AND (
    (ap.lot_size_acres > 10.0 AND t4.built_form_key != 'bt__agriculture')
    OR (ap.lot_size_acres > 3.0 AND ap.zone LIKE '%A%' AND t4.built_form_key != 'bt__agriculture')
  )
  AND (ap.landuse NOT LIKE 'A2%' OR ap.landuse IS NULL);
