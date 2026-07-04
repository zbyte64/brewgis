AUDIT (
  name assert_bft_tier4_area_heuristic,
  dialect postgres
);
-- lot>10ac → ag; 3-10ac+zone%A% → ag
-- Excludes A2% parcels (multi-family) which correctly get mf2to4 from tier4.
-- Reads from tier4 model (apn, built_form_key) and JOINs assessor for landuse.
SELECT
  t4.apn,
  ap.lot_size_acres,
  ap.zone,
  t4.built_form_key,
  CASE
    WHEN ap.lot_size_acres > 10.0 THEN 'agricultural'
    WHEN ap.lot_size_acres > 3.0 AND ap.zone LIKE '%A%' THEN 'agricultural'
    WHEN ap.lot_size_acres > 3.0 AND ap.zone NOT LIKE '%A%' THEN 'detsf_ll'
    WHEN ap.lot_size_acres > 0.15 THEN 'detsf_ll'
    WHEN ap.lot_size_acres > 0.01 THEN 'detsf_sl'
  END AS expected_bft
FROM @this_model t4
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t4.apn = ap.apn
WHERE ap.lot_size_acres IS NOT NULL
  AND t4.built_form_key IS NOT NULL
  AND (
    (ap.lot_size_acres > 10.0 AND t4.built_form_key != 'agricultural')
    OR (ap.lot_size_acres > 3.0 AND ap.zone LIKE '%A%' AND t4.built_form_key != 'agricultural')
  )
  AND (ap.landuse NOT LIKE 'A2%' OR ap.landuse IS NULL);
