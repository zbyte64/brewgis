AUDIT (
  name assert_bft_landuse_A2_falls_through,
  dialect postgres
);
-- A2% landuse → NOT classified at Tier 0 (should be NULL at tier0 level,
-- falling through to Tier 2+ for classification)
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE landuse LIKE 'A2%'
  AND built_form_key IS NOT NULL
  AND built_form_key NOT IN ('mf2to4', 'mf5p');
