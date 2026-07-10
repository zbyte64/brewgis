AUDIT (
  name assert_du_mf_no_sqft,
  dialect postgres
);
-- bt__medium_density_attached_residential + no res_sqft → du=2; bt__high_density_attached_residential + no sqft → du=5
SELECT
  apn,
  built_form_key,
  COALESCE(residential_building_sqft, 0) AS res_sqft,
  du,
  CASE
    WHEN built_form_key = 'bt__medium_density_attached_residential' THEN 2.0
    WHEN built_form_key = 'bt__high_density_attached_residential' THEN 5.0
  END AS expected_du
FROM @this_model
WHERE built_form_key IN ('bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_attached_residential','bt__urban_mid_rise_residential')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND COALESCE(residential_building_sqft, 0) = 0
  AND du IS NOT NULL
  AND ((built_form_key = 'bt__medium_density_attached_residential' AND ABS(du - 2.0) > 0.01)
    OR (built_form_key = 'bt__high_density_attached_residential' AND ABS(du - 5.0) > 0.01));
