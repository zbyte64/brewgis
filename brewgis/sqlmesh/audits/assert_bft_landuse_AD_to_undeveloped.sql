AUDIT (
  name assert_bft_landuse_AD_to_undeveloped,
  dialect postgres
);
-- AD% landuse → undeveloped
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'AD%'
  AND built_form_key != 'undeveloped';
