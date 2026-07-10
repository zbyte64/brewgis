AUDIT (
  name assert_bft_landuse_A2_falls_through,
  dialect postgres
);
-- A2% landuse → must result in a medium-to-high-density attached (MF) residential
-- classification in the FINAL resolved output. Tier0 returns NULL for A2 to let
-- tier2 (Overture building footprints) distinguish MF classes. For parcels
-- without Overture data, tier3 landuse-constrained KNN restricts candidates to
-- MF residential neighbors.
-- JOINs sacog_assessor_parcels since resolver only has (apn, built_form_key, source).
SELECT
  r.apn,
  ap.landuse,
  r.built_form_key
FROM @this_model r
JOIN brewgis.assessor.sacog_assessor_parcels ap ON r.apn = ap.apn
WHERE ap.landuse LIKE 'A2%'
  AND r.built_form_key IS NOT NULL
  AND r.built_form_key NOT IN (
    'bt__medium_density_attached_residential',
    'bt__medium_high_density_attached_residential',
    'bt__high_density_attached_residential',
    'bt__very_high_density_attached_residential',
    'bt__urban_attached_residential',
    'bt__urban_mid_rise_residential'
  );
