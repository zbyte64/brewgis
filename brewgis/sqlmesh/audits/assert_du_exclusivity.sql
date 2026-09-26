AUDIT (
  name assert_du_exclusivity,
  dialect postgres
);
-- du_detsf never co-occurs with du_attsf/du_mf; du_detsf_ll XOR du_detsf_sl
-- (SACOG source: 0 of 393,426 DU parcels).
SELECT
  parcel_id,
  du_detsf,
  du_attsf,
  du_mf,
  du_detsf_ll,
  du_detsf_sl
FROM @this_model
WHERE (COALESCE(du_detsf, 0) > 0 AND (COALESCE(du_attsf, 0) > 0 OR COALESCE(du_mf, 0) > 0))
   OR (COALESCE(du_detsf_ll, 0) > 0 AND COALESCE(du_detsf_sl, 0) > 0);
