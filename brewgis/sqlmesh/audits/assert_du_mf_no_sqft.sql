AUDIT (
  name assert_du_mf_no_sqft,
  dialect postgres
);
-- mf2to4 + no res_sqft → du=2; mf5p + no sqft → du=5
SELECT
  apn,
  built_form_key,
  COALESCE(residential_building_sqft, 0) AS res_sqft,
  du,
  CASE
    WHEN built_form_key = 'mf2to4' THEN 2.0
    WHEN built_form_key = 'mf5p' THEN 5.0
  END AS expected_du
FROM @this_model
WHERE built_form_key IN ('mf2to4', 'mf5p')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND COALESCE(residential_building_sqft, 0) = 0
  AND du IS NOT NULL
  AND ((built_form_key = 'mf2to4' AND ABS(du - 2.0) > 0.01)
    OR (built_form_key = 'mf5p' AND ABS(du - 5.0) > 0.01));
