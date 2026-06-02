AUDIT (
  name assert_du_subtype_sum_equals_du,
  dialect postgres
);
WITH du_subtype_sum AS (
  SELECT
    parcel_id,
    du,
    du_detsf_sl,
    du_detsf_ll,
    du_attsf,
    du_mf2to4,
    du_mf5p,
    COALESCE(du_detsf_sl, 0) + COALESCE(du_detsf_ll, 0)
      + COALESCE(du_attsf, 0) + COALESCE(du_mf2to4, 0)
      + COALESCE(du_mf5p, 0) AS sub_type_sum
  FROM @this
  WHERE du IS NOT NULL AND du > 0
)
SELECT
  parcel_id,
  du,
  sub_type_sum,
  sub_type_sum - du AS delta
FROM du_subtype_sum
WHERE ABS(sub_type_sum - du) > 0.5
