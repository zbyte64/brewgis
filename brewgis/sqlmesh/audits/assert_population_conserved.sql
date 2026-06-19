AUDIT (
  name assert_population_conserved,
  dialect postgres
);
-- Σ(pop per parcel in block) ≈ Census block pop (within 5%)
WITH source AS (
  SELECT SUM(total_population) AS source_pop
  FROM brewgis.staging.census_2020_block
),
allocated AS (
  SELECT SUM(pop) AS allocated_pop
  FROM @this
)
SELECT
  s.source_pop,
  a.allocated_pop,
  ABS(a.allocated_pop - s.source_pop) / GREATEST(s.source_pop, 1) AS pct_diff
FROM source s, allocated a
WHERE s.source_pop > 0
  AND ABS(a.allocated_pop - s.source_pop) / s.source_pop > 0.05;
