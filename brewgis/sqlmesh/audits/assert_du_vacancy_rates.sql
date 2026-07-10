AUDIT (
  name assert_du_vacancy_rates,
  dialect postgres
);
-- SFR bt__ classes → 2.5%, low/medium MF bt__ → 5%, high MF bt__ → 8%
SELECT
  apn,
  built_form_key,
  vacancy_rate,
  CASE
    WHEN built_form_key IN ('bt__low_density_detached_residential','bt__medium_density_detached_residential','bt__medium_high_density_detached_residential','bt__very_low_density_detached_residential','bt__rural_residential','bt__farm_home','bt__mobile_home_park') THEN 0.025
    WHEN built_form_key IN ('bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__urban_attached_residential') THEN 0.050
    WHEN built_form_key IN ('bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_mid_rise_residential') THEN 0.080
    ELSE NULL
  END AS expected_vacancy
FROM @this_model
WHERE built_form_key IN ('bt__low_density_detached_residential','bt__medium_density_detached_residential','bt__medium_high_density_detached_residential','bt__very_low_density_detached_residential','bt__rural_residential','bt__farm_home','bt__mobile_home_park','bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_attached_residential','bt__urban_mid_rise_residential')
  AND ABS(vacancy_rate - CASE
    WHEN built_form_key IN ('bt__low_density_detached_residential','bt__medium_density_detached_residential','bt__medium_high_density_detached_residential','bt__very_low_density_detached_residential','bt__rural_residential','bt__farm_home','bt__mobile_home_park') THEN 0.025
    WHEN built_form_key IN ('bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__urban_attached_residential') THEN 0.050
    WHEN built_form_key IN ('bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_mid_rise_residential') THEN 0.080
  END) > 0.001;
