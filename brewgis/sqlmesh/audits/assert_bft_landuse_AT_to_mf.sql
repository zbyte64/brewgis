AUDIT (
  name assert_bft_landuse_AT_to_mf,
  dialect postgres
);
-- AT% landuse (apartments) → must result in one of the 40-class attached/
-- multi-family residential classifications in the FINAL resolved output.
-- Tier0 returns NULL for AT to let tier2 (Overture building footprints)
-- distinguish densities. For parcels without Overture data, tier3
-- landuse-constrained KNN restricts candidates to attached/multi-family only.
-- JOINs sacog_assessor_parcels since resolver only has (apn, built_form_key, source).
SELECT
  r.apn,
  ap.landuse,
  r.built_form_key
FROM @this_model r
JOIN brewgis.assessor.sacog_assessor_parcels ap ON r.apn = ap.apn
WHERE ap.landuse LIKE 'AT%'
  AND r.built_form_key IS NOT NULL
  AND r.built_form_key NOT IN ('bt__medium_density_attached_residential','bt__medium_high_density_attached_residential','bt__high_density_attached_residential','bt__very_high_density_attached_residential','bt__urban_attached_residential','bt__urban_mid_rise_residential');
