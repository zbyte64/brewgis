AUDIT (
  name assert_bft_landuse_AE_to_commercial,
  dialect postgres
);
-- AE% landuse → commercial
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE landuse LIKE 'AE%'
  AND built_form_key != 'commercial';
