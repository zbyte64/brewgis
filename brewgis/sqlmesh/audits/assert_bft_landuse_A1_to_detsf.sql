AUDIT (
  name assert_bft_landuse_A1_to_detsf,
  dialect postgres
);
-- A1% landuse + lot<0.15 → detsf_sl; A1% landuse + lot≥0.15 → detsf_ll
-- Reads from tier0 model (apn, built_form_key) and JOINs assessor parcels for landuse.
SELECT
  t0.apn,
  ap.landuse,
  ap.lot_size_acres,
  t0.built_form_key,
  CASE
    WHEN ap.lot_size_acres < 0.15 THEN 'detsf_sl'
    ELSE 'detsf_ll'
  END AS expected_bft
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'A1%'
  AND (
    (ap.lot_size_acres < 0.15 AND t0.built_form_key != 'detsf_sl')
    OR (ap.lot_size_acres >= 0.15 AND t0.built_form_key != 'detsf_ll')
  );
