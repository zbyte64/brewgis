AUDIT (
  name assert_bft_landuse_A4_to_detsf,
  dialect postgres
);
-- A4% landuse → bt__medium_density_detached_residential (small lot single family)
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'A4%'
  AND t0.built_form_key != 'bt__medium_density_detached_residential';
