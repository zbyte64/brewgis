AUDIT (
  name assert_bft_landuse_AT_to_mf,
  dialect postgres
);
-- AT% landuse (apartments) → must result in mf2to4 or mf5p classification.
-- Tier0 returns NULL for AT to let tier2 (Overture building footprints)
-- distinguish mf2to4 vs mf5p. For parcels without Overture data, tier3
-- landuse-constrained KNN restricts candidates to mf2to4/mf5p neighbors only.
SELECT
  apn,
  landuse,
  built_form_key
FROM @this_model
WHERE built_form_key_source != 'tier1'
  AND landuse LIKE 'AT%'
  AND built_form_key IS NOT NULL
  AND built_form_key NOT IN ('mf2to4', 'mf5p');
