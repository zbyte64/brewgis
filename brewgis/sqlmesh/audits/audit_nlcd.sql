AUDIT (
  name audit_nlcd,
  dialect postgres
);
SELECT
  id
FROM @this
WHERE id IS NULL
