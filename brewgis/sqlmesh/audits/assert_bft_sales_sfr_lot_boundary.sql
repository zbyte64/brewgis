AUDIT (
  name assert_bft_sales_sfr_lot_boundary,
  dialect postgres
);
-- SFR + lot<0.15 → bt__medium_density_detached_residential; ≥0.15 → bt__low_density_detached_residential
-- Reads from tier1 model (apn, built_form_key) and JOINs sales deduped for property_type.
SELECT
  t1.apn,
  sd.property_type,
  sd.sales_lot_size_acres,
  t1.built_form_key,
  CASE
    WHEN COALESCE(sd.sales_lot_size_acres, 0) < 0.15 THEN 'bt__medium_density_detached_residential'
    ELSE 'bt__low_density_detached_residential'
  END AS expected_bft
FROM @this_model t1
JOIN brewgis.assessor.sacog_assessor_sales_deduped sd ON t1.apn = sd.apn
WHERE (sd.property_type IN ('SFR', 'Single Family Residence') OR sd.property_type LIKE 'Single Family%')
  AND (
    (COALESCE(sd.sales_lot_size_acres, 0) < 0.15 AND t1.built_form_key != 'bt__medium_density_detached_residential')
    OR (COALESCE(sd.sales_lot_size_acres, 0) >= 0.15 AND t1.built_form_key != 'bt__low_density_detached_residential')
  );
