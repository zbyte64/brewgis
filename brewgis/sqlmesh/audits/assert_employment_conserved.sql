AUDIT (
  name assert_employment_conserved,
  dialect postgres
);
-- Σ(emp per parcel in block) ≈ WAC block emp total (within 0.5%)
-- Only count blocks where at least one parcel has emp_dasym_weight > 0,
-- because blocks with no dasymetric weight cannot allocate employment.
WITH
blocks_with_weight AS (
  SELECT DISTINCT cb.geoid
  FROM brewgis.staging.wac_block_projected cb
  JOIN brewgis.base_canvas.base_canvas_demographics bg
    ON ST_Intersects(bg.geometry, cb.geometry)
  WHERE COALESCE(bg.emp_dasym_weight, 0) > 0
),
source AS (
  SELECT SUM(cb.emp) AS source_emp
  FROM brewgis.staging.wac_block_projected cb
  JOIN blocks_with_weight bww ON cb.geoid = bww.geoid
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
