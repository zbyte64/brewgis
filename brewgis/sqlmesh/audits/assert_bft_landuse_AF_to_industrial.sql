AUDIT (
  name assert_bft_landuse_AF_to_industrial,
  dialect postgres
);
-- AF% landuse → industrial
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'AF%'
  AND built_form_key != 'industrial';
