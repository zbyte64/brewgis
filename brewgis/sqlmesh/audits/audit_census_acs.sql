AUDIT (
  name audit_census_acs,
  dialect postgres
);
SELECT
  geoid
FROM @this_model
WHERE geoid IS NULL
