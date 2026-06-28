AUDIT (
  name assert_bft_landuse_commercial_codes_to_commercial,
  dialect postgres
);
-- Commercial landuse prefixes → commercial classification
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND LEFT(landuse, 2) IN ('CA', 'BA', 'BF', 'BC', 'BB', 'BE', 'BD', 'CG', 'MS', 'MU', 'MP')
  AND built_form_key != 'commercial';
