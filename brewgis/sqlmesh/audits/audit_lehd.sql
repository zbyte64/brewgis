AUDIT (
  name audit_lehd,
  dialect postgres
);
SELECT
  w_geocode
FROM @this_model
WHERE w_geocode IS NULL
