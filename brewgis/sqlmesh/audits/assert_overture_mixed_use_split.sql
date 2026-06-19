AUDIT (
  name assert_overture_mixed_use_split,
  dialect postgres
);
-- mixed/unknown class split by levels (levels>1: ground=comm, upper=res)
WITH mixed_use AS (
  SELECT
    apn,
    overture_commercial_sqft,
    overture_residential_sqft,
    building_count,
    max_levels,
    total_footprint_sqft
  FROM @this_model
  WHERE overture_commercial_sqft > 0 AND overture_residential_sqft > 0
)
SELECT
  apn,
  overture_commercial_sqft,
  overture_residential_sqft,
  max_levels,
  total_footprint_sqft,
  CASE
    WHEN COALESCE(max_levels, 0) > 1
    THEN ROUND(total_footprint_sqft / max_levels::double precision)
    ELSE ROUND(total_footprint_sqft * 0.5)
  END AS expected_comm_sqft,
  CASE
    WHEN COALESCE(max_levels, 0) > 1
    THEN ROUND(total_footprint_sqft - total_footprint_sqft / max_levels::double precision)
    ELSE ROUND(total_footprint_sqft * 0.5)
  END AS expected_res_sqft
FROM mixed_use
WHERE (
  COALESCE(max_levels, 0) > 1
  AND (ABS(overture_commercial_sqft - total_footprint_sqft / max_levels::double precision) > 0.01
    OR ABS(overture_residential_sqft - (total_footprint_sqft - total_footprint_sqft / max_levels::double precision)) > 0.01)
)
OR (
  (COALESCE(max_levels, 0) <= 1 OR max_levels IS NULL)
  AND (ABS(overture_commercial_sqft - total_footprint_sqft * 0.5) > 0.01
    OR ABS(overture_residential_sqft - total_footprint_sqft * 0.5) > 0.01)
);
