AUDIT (
  name assert_bft_tier2_sfr_lot_bound,
  dialect postgres
);
-- SFR parcels classified by tier2 must respect lot size boundary:
-- lot ≥ 0.15 acres → bt__low_density_detached_residential; lot < 0.15 → bt__medium_density_detached_residential
--
-- Reads from tier2 model (apn, built_form_key) and JOINs assessor parcels
-- for lot_size_acres and landuse. Excludes A2/AT parcels (multi-family)
-- which correctly get mf classification regardless of lot size.
SELECT
  t2.apn,
  ap.lot_size_acres,
  ap.landuse,
  t2.built_form_key,
  CASE
    WHEN COALESCE(ap.lot_size_acres, 0) < 0.15 THEN 'bt__medium_density_detached_residential'
    ELSE 'bt__low_density_detached_residential'
  END AS expected_bft
FROM @this_model t2
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t2.apn = ap.apn
WHERE t2.built_form_key IN ('bt__medium_density_detached_residential', 'bt__low_density_detached_residential')
  AND LEFT(COALESCE(ap.landuse, ''), 2) NOT IN ('A2', 'AT')
  AND (
    (COALESCE(ap.lot_size_acres, 0) < 0.15 AND t2.built_form_key != 'bt__medium_density_detached_residential')
    OR (COALESCE(ap.lot_size_acres, 0) >= 0.15 AND t2.built_form_key != 'bt__low_density_detached_residential')
  );
