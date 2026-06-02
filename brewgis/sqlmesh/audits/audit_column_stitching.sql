AUDIT (
  name audit_column_stitching,
  dialect postgres
);
SELECT
  id
FROM @this
WHERE id IS NULL
