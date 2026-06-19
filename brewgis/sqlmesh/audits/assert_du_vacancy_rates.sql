AUDIT (
  name assert_du_vacancy_rates,
  dialect postgres
);
-- detsf_sl/ll → 2.5%, attsf/mf2to4 → 5%, mf5p → 8%
SELECT
  apn,
  built_form_key,
  vacancy_rate,
  CASE
    WHEN built_form_key IN ('detsf_sl', 'detsf_ll') THEN 0.025
    WHEN built_form_key IN ('attsf', 'mf2to4') THEN 0.050
    WHEN built_form_key = 'mf5p' THEN 0.080
    ELSE NULL
  END AS expected_vacancy
FROM @this_model
WHERE built_form_key IN ('detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p')
  AND ABS(vacancy_rate - CASE
    WHEN built_form_key IN ('detsf_sl', 'detsf_ll') THEN 0.025
    WHEN built_form_key IN ('attsf', 'mf2to4') THEN 0.050
    WHEN built_form_key = 'mf5p' THEN 0.080
  END) > 0.001;
