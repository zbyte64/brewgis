AUDIT (
  name assert_bft_landuse_commercial_codes_to_commercial,
  dialect postgres
);
-- Commercial landuse prefixes → commercial classification
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE LEFT(ap.landuse, 2) IN ('CA', 'BA', 'BF', 'BC', 'BB', 'BE', 'BD', 'CG', 'MS', 'MU', 'MP')
  AND t0.built_form_key != 'commercial';
