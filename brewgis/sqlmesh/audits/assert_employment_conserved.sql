AUDIT (
  name assert_employment_conserved,
  dialect postgres
);
-- Σ(emp per parcel in block) ≈ WAC block emp total (within 0.5%)
WITH source AS (
  SELECT SUM(emp) AS source_emp
  FROM brewgis.staging.wac_block_projected
),
allocated AS (
  SELECT SUM(emp) AS allocated_emp
  FROM @this_model
)
SELECT
  s.source_emp,
  a.allocated_emp,
  ABS(a.allocated_emp - s.source_emp) / GREATEST(s.source_emp, 1) AS pct_diff
FROM source s, allocated a
WHERE s.source_emp > 0
  AND ABS(a.allocated_emp - s.source_emp) / s.source_emp > 0.005;
