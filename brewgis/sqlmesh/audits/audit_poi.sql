AUDIT (
  name audit_poi,
  dialect postgres
);
SELECT
  name
FROM @this
WHERE name IS NULL
