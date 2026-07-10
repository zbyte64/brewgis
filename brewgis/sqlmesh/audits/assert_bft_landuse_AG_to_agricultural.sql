AUDIT (
  name assert_bft_landuse_AG_to_agricultural,
  dialect postgres
);
-- AG% landuse → bt__agriculture
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'AG%'
  AND t0.built_form_key != 'bt__agriculture';
