AUDIT (
  name assert_bft_landuse_AHAJ_to_civic,
  dialect postgres
);
-- AH%, AJ% landuse → bt__publicquasi_public
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE (ap.landuse LIKE 'AH%' OR ap.landuse LIKE 'AJ%')
  AND t0.built_form_key != 'bt__publicquasi_public';
