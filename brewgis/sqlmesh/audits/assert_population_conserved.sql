AUDIT (
  name assert_population_conserved,
  dialect postgres
);
-- Σ(pop per parcel in block) ≈ Census block pop (within 5%)
--
-- Only counts population from blocks where at least one intersecting parcel
-- has du_pop_dasym_weight > 0. This matches the demographics model's allocation
-- logic: population from blocks without housing-unit dasymetric weight
-- (group quarters, institutional, non-developable land) cannot be allocated
-- to parcels and is correctly excluded from the comparison.
-- Uses a DISTINCT JOIN instead of EXISTS to let the planner use the GIST
-- index on base_canvas_geometry.geometry (EXISTS triggers a Semi Join that
-- materializes the inner scan, bypassing the index).
WITH
blocks_with_weight AS (
  SELECT DISTINCT cb.geoid
  FROM brewgis.staging.census_2020_block_projected cb
  JOIN brewgis.base_canvas.base_canvas_geometry bg
    ON ST_Intersects(bg.geometry, cb.geometry)
  WHERE COALESCE(bg.du_pop_dasym_weight, 0) > 0
),
source AS (
  SELECT SUM(cb.total_population) AS source_pop
  FROM brewgis.staging.census_2020_block_projected cb
  JOIN blocks_with_weight bww ON cb.geoid = bww.geoid
),
allocated AS (
  SELECT SUM(pop) AS allocated_pop
  FROM @this_model
)
SELECT
  s.source_pop,
  a.allocated_pop,
  ABS(a.allocated_pop - s.source_pop) / GREATEST(s.source_pop, 1) AS pct_diff
FROM source s, allocated a
WHERE s.source_pop > 0
  AND ABS(a.allocated_pop - s.source_pop) / s.source_pop > 0.05;
