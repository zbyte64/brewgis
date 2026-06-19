AUDIT (
  name audit_nlcd,
  dialect postgres
);
SELECT
  id
FROM @this_model
WHERE id IS NULL
