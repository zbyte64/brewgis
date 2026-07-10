AUDIT (
  name assert_bft_landuse_industrial_codes_to_industrial,
  dialect postgres
);
-- Industrial landuse prefixes → industrial classification
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE LEFT(ap.landuse, 2) IN ('IA', 'IG', 'IB')
  AND t0.built_form_key != 'bt__light_industrial';
