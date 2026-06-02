AUDIT (
  name audit_census_acs,
  dialect postgres
);
SELECT
  geoid
FROM @this
WHERE geoid IS NULL
