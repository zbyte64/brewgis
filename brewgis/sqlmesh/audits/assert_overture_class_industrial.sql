AUDIT (
  name assert_overture_class_industrial,
  dialect postgres
);
-- industrial class → industrial_building_sqft
SELECT
  apn,
  overture_residential_sqft,
  overture_commercial_sqft,
  overture_industrial_sqft,
  overture_other_sqft
FROM @this_model
WHERE COALESCE(overture_industrial_sqft, 0) > 0
  AND COALESCE(overture_residential_sqft, 0) = 0
  AND COALESCE(overture_commercial_sqft, 0) = 0
  AND COALESCE(overture_other_sqft, 0) = 0;
