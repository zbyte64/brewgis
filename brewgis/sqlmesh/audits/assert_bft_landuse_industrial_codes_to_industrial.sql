AUDIT (
  name assert_bft_landuse_industrial_codes_to_industrial,
  dialect postgres
);
-- Industrial landuse prefixes → industrial classification
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND LEFT(landuse, 2) IN ('IA', 'IG', 'IB')
  AND built_form_key != 'industrial';
