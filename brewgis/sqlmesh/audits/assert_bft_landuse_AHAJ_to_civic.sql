AUDIT (
  name assert_bft_landuse_AHAJ_to_civic,
  dialect postgres
);
-- AH%, AJ% landuse → civic
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE (landuse LIKE 'AH%' OR landuse LIKE 'AJ%')
  AND built_form_key != 'civic';
