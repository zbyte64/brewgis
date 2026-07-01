AUDIT (
  name assert_bft_landuse_civic_codes_to_civic,
  dialect postgres
);
-- Civic landuse prefixes → civic classification
SELECT
  t0.apn,
  ap.landuse,
  t0.built_form_key
FROM @this_model t0
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t0.apn = ap.apn
WHERE LEFT(ap.landuse, 2) IN ('GC', 'GA', 'HJ')
  AND t0.built_form_key != 'civic';
