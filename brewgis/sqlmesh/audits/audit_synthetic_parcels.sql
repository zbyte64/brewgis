AUDIT (
  name audit_synthetic_parcels,
  dialect postgres
);
SELECT
  id,
  geometry
FROM @this_model
WHERE geometry IS NULL
