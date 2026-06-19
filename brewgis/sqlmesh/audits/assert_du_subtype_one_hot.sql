AUDIT (
  name assert_du_subtype_one_hot,
  dialect postgres
);
-- At most one subtype column non-zero per parcel
SELECT
  parcel_id,
  du_subtype,
  du_detsf_sl,
  du_detsf_ll,
  du_attsf,
  du_mf2to4,
  du_mf5p
FROM @this
WHERE (
  CASE WHEN COALESCE(du_detsf_sl, 0) > 0 THEN 1 ELSE 0 END
  + CASE WHEN COALESCE(du_detsf_ll, 0) > 0 THEN 1 ELSE 0 END
  + CASE WHEN COALESCE(du_attsf, 0) > 0 THEN 1 ELSE 0 END
  + CASE WHEN COALESCE(du_mf2to4, 0) > 0 THEN 1 ELSE 0 END
  + CASE WHEN COALESCE(du_mf5p, 0) > 0 THEN 1 ELSE 0 END
) > 1;
