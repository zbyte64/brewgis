AUDIT (
  name assert_overture_class_residential,
  dialect postgres
);
-- residential class → residential_building_sqft
SELECT
  apn,
  overture_residential_sqft,
  overture_commercial_sqft,
  overture_industrial_sqft,
  overture_other_sqft
FROM @this_model
WHERE overture_residential_sqft > 0
  AND overture_commercial_sqft = 0
  AND overture_industrial_sqft = 0
  AND overture_other_sqft = 0;
-- No violation rows means residential-only parcels are correctly classified.
-- Violation would be a row showing cross-classification.
SELECT
  apn,
  overture_residential_sqft,
  overture_commercial_sqft
FROM @this_model
WHERE overture_residential_sqft > 0
  AND overture_commercial_sqft > 0
  AND overture_commercial_sqft > overture_residential_sqft;
