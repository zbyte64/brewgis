AUDIT (
  name assert_bft_landuse_A2_falls_through,
  dialect postgres
);
-- A2% landuse → must result in mf2to4 or mf5p classification.
-- Tier0 intentionally returns NULL for A2 to let tier2 (Overture building
-- footprints) distinguish mf2to4 vs mf5p from building square footage and
-- height. For parcels without Overture data, tier3 landuse-constrained KNN
-- restricts candidates to mf2to4/mf5p neighbors only.
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'A2%'
  AND built_form_key IS NOT NULL
  AND built_form_key NOT IN ('mf2to4', 'mf5p');
