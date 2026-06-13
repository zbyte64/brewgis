AUDIT (
  name audit_pdb_block_group,
  dialect postgres
);

-- Verify PDB block group data quality.

-- 1. Vacancy rate must be between 0 and 1
SELECT
  geoid,
  vacancy_rate
FROM @this
WHERE COALESCE(vacancy_rate, 0) < 0
   OR COALESCE(vacancy_rate, 0) > 1

UNION ALL

-- 2. Group quarters population must be non-negative
SELECT
  geoid,
  group_quarters_pop
FROM @this
WHERE group_quarters_pop < 0

UNION ALL

-- 3. Low response score must be between 0 and 1
SELECT
  geoid,
  low_response_score
FROM @this
WHERE low_response_score IS NOT NULL
  AND (low_response_score < 0 OR low_response_score > 1)
