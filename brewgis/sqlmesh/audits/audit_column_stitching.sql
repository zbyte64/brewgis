AUDIT (
  name audit_column_stitching,
  dialect postgres
);
SELECT
  id
FROM @this_model
WHERE id IS NULL
