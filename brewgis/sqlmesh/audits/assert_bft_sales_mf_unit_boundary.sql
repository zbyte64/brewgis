AUDIT (
  name assert_bft_sales_mf_unit_boundary,
  dialect postgres
);
-- MF + 2-4 units → bt__medium_density_attached_residential; 5+ → bt__high_density_attached_residential
-- Reads from tier1 model (apn, built_form_key) and JOINs sales deduped for property_type + units.
SELECT
  t1.apn,
  sd.property_type,
  sd.units,
  t1.built_form_key,
  CASE
    WHEN COALESCE(sd.units, 0) BETWEEN 2 AND 4 THEN 'bt__medium_density_attached_residential'
    WHEN COALESCE(sd.units, 0) >= 5 THEN 'bt__high_density_attached_residential'
  END AS expected_bft
FROM @this_model t1
JOIN brewgis.assessor.sacog_assessor_sales_deduped sd ON t1.apn = sd.apn
WHERE (sd.property_type IN ('MF', 'Multiple Family Residence') OR sd.property_type LIKE 'Multiple Family%')
  AND sd.units IS NOT NULL AND sd.units >= 2
  AND (
    (COALESCE(sd.units, 0) BETWEEN 2 AND 4 AND t1.built_form_key != 'bt__medium_density_attached_residential')
    OR (COALESCE(sd.units, 0) >= 5 AND t1.built_form_key != 'bt__high_density_attached_residential')
  );
