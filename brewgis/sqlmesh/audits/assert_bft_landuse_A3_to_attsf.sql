AUDIT (
  name assert_bft_landuse_A3_to_attsf,
  dialect postgres
);
-- A3% landuse → attsf
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE landuse LIKE 'A3%'
  AND built_form_key != 'attsf';
