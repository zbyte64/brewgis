AUDIT (
  name assert_du_sfr_equals_one,
  dialect postgres
);
-- detsf_sl/ll → du=1
SELECT
  apn,
  built_form_key,
  du
FROM @this_model
WHERE built_form_key IN ('detsf_sl', 'detsf_ll')
  AND (assessor_units IS NULL OR assessor_units <= 0)
  AND ABS(du - 1.0) > 0.01;
