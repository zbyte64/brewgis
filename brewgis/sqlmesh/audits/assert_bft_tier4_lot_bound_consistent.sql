AUDIT (
  name assert_bft_tier4_lot_bound_consistent,
  dialect postgres
);
-- Tier4 SL/LL lot boundary (0.4 ac for detsf_ll) MUST equal tier1/tier0
-- boundary (0.15 ac). When tier4 produces detsf_sl for a parcel with
-- lot in [0.15, 0.4), it mismatches what tier1 would produce.
--
-- Any row returned is a violation.
SELECT
  t4.apn,
  ap.lot_size_acres,
  ap.zone,
  t4.built_form_key
FROM @this_model t4
JOIN brewgis.assessor.sacog_assessor_parcels ap ON t4.apn = ap.apn
WHERE t4.built_form_key = 'detsf_sl'
  AND ap.lot_size_acres >= 0.15
  AND ap.lot_size_acres < 0.4
  AND (ap.landuse NOT LIKE 'A2%' OR ap.landuse IS NULL);
