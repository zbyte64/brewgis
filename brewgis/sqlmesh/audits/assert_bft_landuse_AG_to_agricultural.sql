AUDIT (
  name assert_bft_landuse_AG_to_agricultural,
  dialect postgres
);
-- AG% landuse → agricultural
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'AG%'
  AND built_form_key != 'agricultural';
