AUDIT (
  name assert_bft_landuse_AD_to_undeveloped,
  dialect postgres
);
-- AD% landuse → undeveloped
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'AD%'
  AND t0.built_form_key != 'undeveloped';
