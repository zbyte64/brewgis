AUDIT (
  name audit_acs_block_group,
  dialect postgres
);
SELECT
  geoid,
  total_population
FROM @this_model
WHERE COALESCE(total_population, 0) < 0
