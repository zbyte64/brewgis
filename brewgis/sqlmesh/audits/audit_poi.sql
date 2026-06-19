AUDIT (
  name audit_poi,
  dialect postgres
);
SELECT
  name
FROM @this_model
WHERE name IS NULL
