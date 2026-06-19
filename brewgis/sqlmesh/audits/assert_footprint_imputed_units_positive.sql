AUDIT (
  name assert_footprint_imputed_units_positive,
  dialect postgres
);
SELECT
  apn,
  imputed_units,
  imputed_living_sqft,
  imputed_building_sqft
FROM @this_model
WHERE imputed_property_type IS NOT NULL
  AND (
      imputed_units < 0
   OR imputed_living_sqft < 0
   OR imputed_building_sqft < 0
  )
