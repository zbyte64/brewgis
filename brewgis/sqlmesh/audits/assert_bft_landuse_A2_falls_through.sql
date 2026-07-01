AUDIT (
  name assert_bft_landuse_A2_falls_through,
  dialect postgres
);
-- A2% landuse → must result in mf2to4 or mf5p classification in the FINAL
-- resolved output. Tier0 returns NULL for A2 to let tier2 (Overture building
-- footprints) distinguish mf2to4 vs mf5p. For parcels without Overture data,
-- tier3 landuse-constrained KNN restricts candidates to mf2to4/mf5p neighbors.
-- JOINs sacog_assessor_parcels since resolver only has (apn, built_form_key, source).
SELECT
  r.apn,
  ap.landuse,
  r.built_form_key
FROM @this_model r
JOIN brewgis.assessor.sacog_assessor_parcels ap ON r.apn = ap.apn
WHERE ap.landuse LIKE 'A2%'
  AND r.built_form_key IS NOT NULL
  AND r.built_form_key NOT IN ('mf2to4', 'mf5p');
