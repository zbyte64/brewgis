AUDIT (
  name assert_bft_landuse_AT_to_mf,
  dialect postgres
);
-- AT% landuse (apartments) → must result in mf2to4 or mf5p classification in
-- the FINAL resolved output. Tier0 returns NULL for AT to let tier2 (Overture
-- building footprints) distinguish mf2to4 vs mf5p. For parcels without Overture
-- data, tier3 landuse-constrained KNN restricts candidates to mf2to4/mf5p only.
-- JOINs sacog_assessor_parcels since resolver only has (apn, built_form_key, source).
SELECT
  r.apn,
  ap.landuse,
  r.built_form_key
FROM @this_model r
JOIN brewgis.assessor.sacog_assessor_parcels ap ON r.apn = ap.apn
WHERE ap.landuse LIKE 'AT%'
  AND r.built_form_key IS NOT NULL
  AND r.built_form_key NOT IN ('mf2to4', 'mf5p');
