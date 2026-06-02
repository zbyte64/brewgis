AUDIT (
  name audit_synthetic_parcels,
  dialect postgres
);
SELECT
  id,
  geometry
FROM @this
WHERE geometry IS NULL
