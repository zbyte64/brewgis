AUDIT (
  name assert_parcel_dasymetric_weights_row_count,
  dialect postgres
);

-- Verify parcel_dasymetric_weights has a reasonable number of rows
-- for Sacramento County (~510K parcels). Outside this range indicates
-- duplicates, load failures, or upstream data issues.
WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt < 500000 OR cnt > 520000;
