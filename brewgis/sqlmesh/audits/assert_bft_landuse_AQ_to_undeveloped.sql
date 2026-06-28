AUDIT (
  name assert_bft_landuse_AQ_to_undeveloped,
  dialect postgres
);
-- AQ% landuse → undeveloped
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'AQ%'
  AND built_form_key != 'undeveloped';
