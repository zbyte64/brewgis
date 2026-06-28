AUDIT (
  name assert_bft_landuse_civic_codes_to_civic,
  dialect postgres
);
-- Civic landuse prefixes → civic classification
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND LEFT(landuse, 2) IN ('GC', 'GA', 'HJ')
  AND built_form_key != 'civic';
