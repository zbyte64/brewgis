AUDIT (
  name assert_bft_landuse_AQ_to_undeveloped,
  dialect postgres
);
-- AQ% landuse → undeveloped
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'AQ%'
  AND t0.built_form_key != 'undeveloped';
