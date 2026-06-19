AUDIT (
  name assert_du_subtype_sum_equals_du,
  dialect postgres
);
-- Σ(du_subtypes) = du (within tolerance)
SELECT
  parcel_id,
  du,
  du_detsf_sl + du_detsf_ll + du_attsf + du_mf2to4 + du_mf5p AS subtype_sum,
  ABS(du - (du_detsf_sl + du_detsf_ll + du_attsf + du_mf2to4 + du_mf5p)) AS diff
FROM @this
WHERE du IS NOT NULL AND du > 0
  AND ABS(du - (COALESCE(du_detsf_sl, 0) + COALESCE(du_detsf_ll, 0)
    + COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0) + COALESCE(du_mf5p, 0))) > 0.5;
