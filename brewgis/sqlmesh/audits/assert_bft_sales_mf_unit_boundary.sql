AUDIT (
  name assert_bft_sales_mf_unit_boundary,
  dialect postgres
);
-- MF + 2-4 units → mf2to4; 5+ → mf5p
SELECT
  apn,
  property_type,
  units,
  built_form_key,
  CASE
    WHEN COALESCE(units, 0) BETWEEN 2 AND 4 THEN 'mf2to4'
    WHEN COALESCE(units, 0) >= 5 THEN 'mf5p'
  END AS expected_bft
FROM @this_model
WHERE (property_type IN ('MF', 'Multiple Family Residence') OR property_type LIKE 'Multiple Family%')
  AND units IS NOT NULL AND units >= 2
  AND (
    (COALESCE(units, 0) BETWEEN 2 AND 4 AND built_form_key != 'mf2to4')
    OR (COALESCE(units, 0) >= 5 AND built_form_key != 'mf5p')
  );
