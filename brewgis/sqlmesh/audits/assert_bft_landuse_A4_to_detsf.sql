AUDIT (
  name assert_bft_landuse_A4_to_detsf,
  dialect postgres
);
-- A4% landuse → detsf_sl (small lot single family)
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'A4%'
  AND built_form_key != 'detsf_sl';
