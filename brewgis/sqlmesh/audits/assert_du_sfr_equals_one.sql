AUDIT (
  name assert_du_sfr_equals_one,
  dialect postgres
);
-- Single-family residential (SF) built forms → du=1
SELECT
  apn,
  built_form_key,
  du
FROM @this_model
WHERE built_form_key IN ('bt__low_density_detached_residential','bt__medium_density_detached_residential','bt__medium_high_density_detached_residential','bt__very_low_density_detached_residential','bt__rural_residential','bt__farm_home','bt__mobile_home_park')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND ABS(du - 1.0) > 0.01;
