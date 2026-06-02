AUDIT (
  name assert_du_subtype_allocation,
  dialect postgres
);
SELECT
  parcel_id,
  du_subtype,
  du_detsf_sl,
  du_detsf_ll,
  du_attsf,
  du_mf2to4,
  du_mf5p
FROM @this
WHERE
  du_subtype IS NOT NULL
  AND (
    (du_subtype = 'attsf' AND (COALESCE(du_detsf_sl, 0) > 0.01 OR COALESCE(du_detsf_ll, 0) > 0.01))
    OR (du_subtype = 'mf2to4' AND COALESCE(du_mf5p, 0) > 0.01)
    OR (du_subtype = 'detsf_sl' AND (COALESCE(du_attsf, 0) > 0.01 OR COALESCE(du_mf2to4, 0) > 0.01))
    OR (du_subtype = 'detsf_ll' AND (COALESCE(du_attsf, 0) > 0.01 OR COALESCE(du_mf2to4, 0) > 0.01))
    OR (du_subtype = 'mf5p' AND COALESCE(du_mf2to4, 0) > 0.01)
  )
