AUDIT (
  name assert_bft_landuse_A3_to_attsf,
  dialect postgres
);
-- A3% landuse → attsf
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE ap.landuse LIKE 'A3%'
  AND t0.built_form_key != 'attsf';
