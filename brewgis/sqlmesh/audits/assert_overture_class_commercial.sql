AUDIT (
  name assert_overture_class_commercial,
  dialect postgres
);
-- commercial class → commercial_building_sqft
SELECT
  parcel_id,
  residential_building_sqft,
  commercial_building_sqft,
  industrial_building_sqft,
  other_building_sqft
FROM @this
WHERE COALESCE(commercial_building_sqft, 0) > 0
  AND COALESCE(residential_building_sqft, 0) = 0
  AND COALESCE(other_building_sqft, 0) = 0;
